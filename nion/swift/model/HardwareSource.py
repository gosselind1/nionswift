"""
This module defines classes for handling live data sources.

A HardwareSource represents a source of data and metadata frames.

An AcquisitionTask tracks the state for a particular acquisition of a frame or sequence of frames.

The HardwareSourceManager allows callers to register and unregister hardware sources.

This module also defines individual functions that can be used to collect data from hardware sources.
"""

# system imports
import collections
import configparser
import contextlib
import copy
import datetime
import functools
import gettext
import logging
import os
import threading
import time
import traceback
import uuid

# typing
from typing import Dict

# local imports
from nion.swift.model import Calibration
from nion.swift.model import DataAndMetadata
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding
from nion.swift.model import Image
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility
from nion.ui import Event
from nion.ui import Unicode

_ = gettext.gettext


# Keeps track of all registered hardware sources and instruments.
# Also keeps track of aliases between hardware sources and logical names.
class HardwareSourceManager(metaclass=Utility.Singleton):
    def __init__(self):
        super(HardwareSourceManager, self).__init__()
        self.hardware_sources = []
        self.instruments = []
        # we create a list of callbacks for when a hardware
        # source is added or removed
        self.hardware_source_added_event = Event.Event()
        self.hardware_source_removed_event = Event.Event()
        self.aliases_updated = []
        # aliases are shared between hardware sources and instruments
        self.__aliases = {}

    def close(self):
        self._close_hardware_sources()
        self._close_instruments()

    def _close_instruments(self):
        for instrument in self.instruments:
            if hasattr(instrument, "close"):
                instrument.close()
        self.instruments = []

    def _close_hardware_sources(self):
        for hardware_source in self.hardware_sources:
            if hasattr(hardware_source, "close"):
                hardware_source.close()
        self.hardware_sources = []

    def _reset(self):  # used for testing to start from scratch
        self.hardware_sources = []
        self.instruments = []
        self.hardware_source_added_event = Event.Event()
        self.hardware_source_removed_event = Event.Event()
        self.__aliases = {}

    def register_hardware_source(self, hardware_source):
        self.hardware_sources.append(hardware_source)
        self.hardware_source_added_event.fire(hardware_source)

    def unregister_hardware_source(self, hardware_source):
        self.hardware_sources.remove(hardware_source)
        self.hardware_source_removed_event.fire(hardware_source)

    def register_instrument(self, instrument_id, instrument):
        instrument.instrument_id = instrument_id
        self.instruments.append(instrument)

    def unregister_instrument(self, instrument_id):
        for instrument in self.instruments:
            if instrument.instrument_id == instrument_id:
                instrument.instrument_id = None
                self.instruments.remove(instrument)
                break

    def abort_all_and_close(self):
        for hardware_source in copy.copy(self.hardware_sources):
            hardware_source.abort_playing()

    def get_all_instrument_ids(self):
        instrument_ids = set()
        instrument_ids.update(list(instrument.instrument_id for instrument in self.instruments))
        for alias in self.__aliases.keys():
            resolved_alias = self.get_instrument_by_id(alias)
            if resolved_alias:
                instrument_ids.add(alias)
        return instrument_ids

    def get_all_hardware_source_ids(self):
        hardware_source_ids = set()
        hardware_source_ids.update(list(hardware_source.hardware_source_id for hardware_source in self.hardware_sources))
        for alias in self.__aliases.keys():
            resolved_alias = self.get_hardware_source_for_hardware_source_id(alias)
            if resolved_alias:
                hardware_source_ids.add(alias)
        return hardware_source_ids

    def __get_info_for_instrument_id(self, instrument_id):
        display_name = Unicode.u()
        seen_instrument_ids = []  # prevent loops, just so we don't get into endless loop in case of user error
        while instrument_id in self.__aliases and instrument_id not in seen_instrument_ids:
            seen_instrument_ids.append(instrument_id)  # must go before next line
            instrument_id, display_name = self.__aliases[instrument_id]
        for instrument in self.instruments:
            if instrument.instrument_id == instrument_id:
                return instrument, display_name
        return None

    # may return None
    def get_instrument_by_id(self, instrument_id):
        info = self.__get_info_for_instrument_id(instrument_id)
        if info:
            instrument, display_name = info
            return instrument
        return None

    def __get_info_for_hardware_source_id(self, hardware_source_id):
        display_name = Unicode.u()
        seen_hardware_source_ids = []  # prevent loops, just so we don't get into endless loop in case of user error
        while hardware_source_id in self.__aliases and hardware_source_id not in seen_hardware_source_ids:
            seen_hardware_source_ids.append(hardware_source_id)  # must go before next line
            hardware_source_id, display_name = self.__aliases[hardware_source_id]
        for hardware_source in self.hardware_sources:
            if hardware_source.hardware_source_id == hardware_source_id:
                return hardware_source, display_name
        return None

    def get_hardware_source_for_hardware_source_id(self, hardware_source_id):
        info = self.__get_info_for_hardware_source_id(hardware_source_id)
        if info:
            hardware_source, display_name = info
            return hardware_source
        return None

    def make_instrument_alias(self, instrument_id, alias_instrument_id, display_name):
        """ Configure an alias.

            Callers can use the alias to refer to the instrument or hardware source.
            The alias should be lowercase, no spaces. The display name may be used to display alias to
            the user. Neither the original instrument or hardware source id and the alias id should ever
            be visible to end users.

            :param str instrument_id: the hardware source id (lowercase, no spaces)
            :param str alias_instrument_id: the alias of the hardware source id (lowercase, no spaces)
            :param str display_name: the display name for the alias
        """
        self.__aliases[alias_instrument_id] = (instrument_id, display_name)
        for f in self.aliases_updated:
            f()


Channel = collections.namedtuple("Channel", ["channel_id", "index", "name", "data_element"])

ChannelData = collections.namedtuple("Channel", ["channel_id", "index", "name", "data_and_calibration", "state", "sub_area"])


class AcquisitionTask:
    """Basic acquisition task carries out acquisition repeatedly during an acquisition loop, keeping track of state.

    The caller controls the state of the task by calling the following methods:
        execute: start or continue acquisition, should be called repeatedly until is_finished is True
        suspend: suspend the state of acquisition, returns bool for success
        resume: resume a suspended state of acquisition
        stop: notify that acquisition should stop after end of current frame
        abort: notify that acquisition should abort as soon as possible

    In addition the caller can query the state of acquisition using the following method:
        is_finished: whether acquisition has finished or not

    Finally, the caller can listen to the following events:
        finished_event(): fired when acquisition is finished, successful or not
        data_elements_changed_event(data_elements, is_continuous, view_id, is_complete, is_stopping):
            fired when data elements change. the state of acquisition is passed too.

    Subclasses can override these methods to implement the acquisition:
        _start_acquisition: called once at the beginning of this task
        _abort_acquisition: called when the caller has requested to abort acquisition
        _suspend_acquisition: called when the caller has requested to suspend acquisition
        _resume_acquisition: called when the caller has requested to resume a suspended acquisition
        _mark_acquisition: marks the acquisition to stop at end of current frame
        _acquire_data_elements: return list of data elements, with metadata indicating completion status
        _stop_acquisition: final call to indicate acquisition has stopped; subclasses should synchronize stop here
    """

    def __init__(self, hardware_source, hardware_source_id, continuous: bool):
        self.__hardware_source = hardware_source
        self.__started = False
        self.__finished = False
        self.__is_suspended = False
        self.__aborted = False
        self.__is_stopping = False
        self.__is_continuous = continuous
        self.__last_acquire_time = None
        self.__minimum_period = 1/1000.0
        self.__frame_index = 0
        self.__view_id = str(uuid.uuid4()) if not continuous else hardware_source_id
        self._test_acquire_exception = None
        self._test_acquire_hook = None
        self.finished_event = Event.Event()
        self.data_elements_changed_event = Event.Event()

    def __mark_as_finished(self):
        self.__finished = True
        self.data_elements_changed_event.fire(list(), self.__is_continuous, self.__view_id, False, self.__is_stopping)
        self.finished_event.fire()

    # called from the hardware source
    def execute(self):
        # first start the task
        if not self.__started:
            try:
                self.__start()
            except Exception as e:
                # the task is finished if it doesn't start
                self.__mark_as_finished()
                raise
            self.__started = True
            # logging.debug("%s started", self)
        if self.__is_suspended:
            try:
                self.resume()
            finally:
                self.__is_suspended = False
        if not self.__finished:
            try:
                # if aborted, abort here
                if self.__aborted:
                    # logging.debug("%s aborted", self)
                    self._abort_acquisition()
                    # logging.debug("%s stopped", self)
                    self._mark_acquisition()
                    self._stop_acquisition()
                    self.__mark_as_finished()
                # otherwise execute the task
                else:
                    complete = self.__execute_acquire_data_elements()
                    # logging.debug("%s executed %s", self, complete)
                    if complete and (self.__is_stopping or not self.__is_continuous):
                        # logging.debug("%s finished", self)
                        self._stop_acquisition()
                        self.__mark_as_finished()
            except Exception as e:
                # the task is finished if it doesn't execute
                # logging.debug("exception")
                self.__mark_as_finished()
                raise

    # called from the hardware source
    def suspend(self) -> bool:
        if not self.__is_suspended:
            self.__is_suspended = True
            return self._suspend_acquisition()
        return True

    # called from the hardware source
    def resume(self):
        self._resume_acquisition()

    @property
    def is_finished(self):
        return self.__finished

    # called from the hardware source
    def abort(self):
        self.__aborted = True

    # called from the hardware source
    def stop(self):
        self.__is_stopping = True
        self._mark_acquisition()

    def __start(self):
        if not self._start_acquisition():
            self.abort()
        self.__last_acquire_time = time.time() - self.__minimum_period

    def __execute_acquire_data_elements(self):
        # with Utility.trace(): # (min_elapsed=0.0005, discard="anaconda"):
        # impose maximum frame rate so that acquire_data_elements can't starve main thread
        elapsed = time.time() - self.__last_acquire_time
        time.sleep(max(0.0, self.__minimum_period - elapsed))

        if self._test_acquire_hook:
            self._test_acquire_hook()

        partial_data_elements = self._acquire_data_elements()
        assert partial_data_elements is not None  # data_elements should never be empty

        # update frame_index if not supplied
        for data_element in partial_data_elements:
            data_element.setdefault("properties", dict()).setdefault("frame_index", self.__frame_index)

        # merge the data if necessary
        data_elements = self.__data_elements
        if not data_elements:
            data_elements = copy.copy(partial_data_elements)
        else:
            for partial_data_element, data_element in zip(partial_data_elements, data_elements):
                existing_sub_area = data_element.get("sub_area", ((0, 0), data_element["data"].shape))
                new_sub_area = partial_data_element.get("sub_area", ((0, 0), partial_data_element.get("data").shape))
                existing_top = existing_sub_area[0][0]
                existing_height = existing_sub_area[1][0]
                existing_left = existing_sub_area[0][1]
                existing_width = existing_sub_area[1][1]
                existing_bottom = existing_top + existing_height
                existing_right = existing_left + existing_width
                new_top = new_sub_area[0][0]
                new_bottom = new_top + new_sub_area[1][0]
                new_width = new_sub_area[1][1]
                assert new_top <= existing_bottom  # don't skip sub-areas
                if new_top > 0:
                    assert new_width == existing_width  # only support full width sub-areas
                if new_top > 0:
                    y_slice = slice(existing_top, new_top)
                    x_slice = slice(existing_left, existing_right)
                    sub_area_slice = y_slice, x_slice
                    partial_data_element["data"][sub_area_slice] = data_element["data"][sub_area_slice]
                    partial_data_element["sub_area"] = (existing_top, existing_left), (new_bottom - existing_top, existing_width)
                data_elements = partial_data_elements

        # record the last acquisition time
        self.__last_acquire_time = time.time()

        # figure out whether all data elements are complete
        complete = True
        for data_element in data_elements:
            sub_area = data_element.get("sub_area")
            state = data_element.get("state", "complete")
            if not (sub_area is None or state == "complete"):
                complete = False
                break

        # notify that data elements have changed
        self.data_elements_changed_event.fire(data_elements, self.__is_continuous, self.__view_id, complete, self.__is_stopping)

        if complete:
            self.__frame_index += 1
        else:
            # need to save data elements for next time through loop
            self.__data_elements = data_elements

        return complete

    # override these routines. the default implementation is to
    # call back to the hardware source.

    def _start_acquisition(self) -> bool:
        self.__data_elements = None
        return self.__hardware_source.start_acquisition() if self.__hardware_source else True

    def _abort_acquisition(self) -> None:
        self.__data_elements = None
        if self.__hardware_source:
            self.__hardware_source.abort_acquisition()

    def _suspend_acquisition(self) -> bool:
        self.__data_elements = None
        return self.__hardware_source.suspend_acquisition() if self.__hardware_source else False

    def _resume_acquisition(self) -> None:
        self.__data_elements = None
        if self.__hardware_source:
            self.__hardware_source.resume_acquisition()

    def _mark_acquisition(self) -> None:
        if self.__hardware_source:
            self.__hardware_source.mark_acquisition()

    def _stop_acquisition(self) -> None:
        self.__data_elements = None
        if self.__hardware_source:
            self.__hardware_source.stop_acquisition()

    def _acquire_data_elements(self):
        assert self.__hardware_source
        return self.__hardware_source.acquire_data_elements()


class HardwareSource:
    """Represents a source of data and metadata frames.

    The hardware source generates data on a background thread.
    """

    def __init__(self, hardware_source_id, display_name):
        super(HardwareSource, self).__init__()
        self.hardware_source_id = hardware_source_id
        self.display_name = display_name
        self.channel_count = 1
        self.features = dict()
        self.data_elements_available_event = Event.Event()
        self.abort_event = Event.Event()
        self.acquisition_state_changed_event = Event.Event()
        self.data_item_states_changed_event = Event.Event()
        self.channels_data_updated_event = Event.Event()
        self.__acquire_thread_break = False
        self.__acquire_thread_trigger = threading.Event()
        self.__tasks = dict()  # type: Dict[str, AcquisitionTask]
        self.__data_elements_changed_event_listeners = dict()
        self.__view_data_elements_changed_event_listener = None
        self.__record_data_elements_changed_event_listener = None
        self.__acquire_thread = threading.Thread(target=self.__acquire_thread_loop)
        self.__acquire_thread.daemon = True
        self.__acquire_thread.start()
        self._test_acquire_exception = None
        self._test_acquire_hook = None

    def close(self):
        # when overriding hardware source close, the acquisition loop may still be running
        # so nothing can be changed here that will make the acquisition loop fail.
        self.__acquire_thread_break = True
        self.__acquire_thread_trigger.set()
        # acquire_thread should always be non-null here, otherwise close was called twice.
        self.__acquire_thread.join()
        self.__acquire_thread = None

    def __acquire_thread_loop(self):
        # acquire_thread_trigger should be set whenever the task list change.
        while self.__acquire_thread_trigger.wait():
            self.__acquire_thread_trigger.clear()
            # record task gets highest priority
            acquire_thread_break = self.__acquire_thread_break
            suspend_task_id_list = list()
            task_id = None
            if self.__tasks.get('idle'):
                task_id = 'idle'
            if self.__tasks.get('view'):
                task_id = 'view'
                suspend_task_id_list.append('idle')
            if self.__tasks.get('record'):
                task_id = 'record'
                suspend_task_id_list.append('idle')
                suspend_task_id_list.append('view')
            if task_id:
                task = self.__tasks[task_id]
                if acquire_thread_break:
                    task.abort()
                    self.abort_event.fire()
                else:
                    try:
                        for suspend_task_id in suspend_task_id_list:
                            suspend_task = self.__tasks.get(suspend_task_id)
                            if suspend_task:
                                suspend_task.suspend()
                        task.execute()
                    except Exception as e:
                        task.abort()
                        self.abort_event.fire()
                        if callable(self._test_acquire_exception):
                            self._test_acquire_exception(e)
                        else:
                            import traceback
                            logging.debug("{} Error: {}".format(task_id.capitalize(), e))
                            traceback.print_exc()
                    if task.is_finished:
                        del self.__tasks[task_id]
                        self.__data_elements_changed_event_listeners[task_id].close()
                        del self.__data_elements_changed_event_listeners[task_id]
                        self.acquisition_state_changed_event.fire(False)
                    self.__acquire_thread_trigger.set()
            if acquire_thread_break:
                break

    # subclasses can implement this method which is called when acquisition starts.
    # return True if successful, False if not.
    # must be thread safe
    def start_acquisition(self) -> bool:
        return True

    # subclasses can implement this method which is called when acquisition aborts.
    # must be thread safe
    def abort_acquisition(self):
        pass

    # subclasses can implement this method which is called when acquisition is suspended for higher priority acquisition.
    # if a view starts during a record, it will start in a suspended state and resume will be called without a prior
    # suspend.
    # must be thread safe
    def suspend_acquisition(self) -> bool:
        return False

    # subclasses can implement this method which is called when acquisition is resumed from higher priority acquisition.
    # if a view starts during a record, it will start in a suspended state and resume will be called without a prior
    # suspend.
    # must be thread safe
    def resume_acquisition(self):
        pass

    # subclasses can implement this method which is called when acquisition is marked for stopping.
    # subclasses that feature a continuous mode will need implement this method so that continuous
    # mode is marked for stopping at the end of the current frame.
    # must be thread safe
    def mark_acquisition(self):
        pass

    # subclasses can implement this method which is called when acquisition stops.
    # must be thread safe
    def stop_acquisition(self):
        pass

    # subclasses are expected to implement this function efficiently since it will
    # be repeatedly called. in practice that means that subclasses MUST sleep (directly
    # or indirectly) unless the data is immediately available, which it shouldn't be on
    # a regular basis. it is an error for this function to return an empty list of data_elements.
    # this method can throw exceptions, it will result in the acquisition loop being aborted.
    # returns a tuple of a list of data elements.
    # must be thread safe
    def acquire_data_elements(self):
        raise NotImplementedError()

    # subclasses can implement this method which is called when the data items used for acquisition change.
    def data_item_states_changed(self, data_item_states):
        pass

    # create the view task
    def __create_acquisition_view_task(self):
        return AcquisitionTask(self, self.hardware_source_id, True)

    # create the view task
    def __create_acquisition_record_task(self):
        return AcquisitionTask(self, self.hardware_source_id, False)

    # call this to set the view task
    # thread safe
    def __set_active_view_task(self, view_task):
        self.__view_data_elements_changed_event_listener = view_task.data_elements_changed_event.listen(self.__data_elements_changed)
        self.__tasks['view'] = view_task
        self.__acquire_thread_trigger.set()
        self.acquisition_state_changed_event.fire(True)

    # call this to set the record task
    # thread safe
    def __set_active_record_task(self, record_task):
        self.__record_data_elements_changed_event_listener = record_task.data_elements_changed_event.listen(self.__data_elements_changed)
        self.__tasks['record'] = record_task
        self.__acquire_thread_trigger.set()
        self.acquisition_state_changed_event.fire(True)

    # data_elements is a list of data_elements; may be an empty list
    # thread safe
    def __data_elements_changed(self, data_elements, is_continuous, view_id, is_complete, is_stopping):
        channels_data = list()
        for channel_index, data_element in enumerate(data_elements):
            assert data_element is not None
            channel_id = data_element.get("channel_id")
            channel_name = data_element.get("channel_name")
            data_and_calibration = convert_data_element_to_data_and_metadata(data_element)
            channel_state = data_element.get("state", "complete")
            if channel_state != "complete" and is_stopping:
                channel_state = "marked"
            sub_area = data_element.get("sub_area")
            channels_data.append(ChannelData(channel_id=channel_id, index=channel_index, name=channel_name,
                                        data_and_calibration=data_and_calibration, state=channel_state,
                                        sub_area=sub_area))
        self.channels_data_updated_event.fire(view_id, not is_continuous, channels_data)
        if is_complete:
            self.data_elements_available_event.fire(data_elements)

    # return whether task is running
    def is_task_running(self, task_id: str) -> bool:
        return task_id in self.__tasks

    # call this to start the task running
    # not thread safe
    def start_task(self, task_id: str, task: AcquisitionTask) -> None:
        assert not task in self.__tasks.values()
        assert not task_id in self.__tasks
        assert task_id in ('idle', 'view', 'record')
        self.__data_elements_changed_event_listeners[task_id] = task.data_elements_changed_event.listen(self.__data_elements_changed)
        self.__tasks[task_id] = task
        self.__acquire_thread_trigger.set()
        self.acquisition_state_changed_event.fire(True)

    # call this to stop task immediately
    # not thread safe
    def abort_task(self, task_id: str) -> None:
        task = self.__tasks.get(task_id)
        assert task is not None
        task.abort()
        self.abort_event.fire()

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_task(self, task_id: str) -> None:
        task = self.__tasks.get(task_id)
        assert task is not None
        task.stop()

    # return whether acquisition is running
    @property
    def is_playing(self):
        return self.is_task_running('view')

    # call this to start acquisition
    # not thread safe
    def start_playing(self):
        if not self.is_playing:
            view_task = self.__create_acquisition_view_task()
            view_task._test_acquire_hook = self._test_acquire_hook
            self.start_task('view', view_task)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_playing(self):
        if self.is_playing:
            self.abort_task('view')

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_playing(self):
        if self.is_playing:
            self.stop_task('view')

    # return whether acquisition is running
    @property
    def is_recording(self):
        return self.is_task_running('record')

    # call this to start acquisition
    # thread safe
    def start_recording(self):
        if not self.is_recording:
            record_task = self.__create_acquisition_record_task()
            self.start_task('record', record_task)

    # call this to stop acquisition immediately
    # not thread safe
    def abort_recording(self):
        if self.is_recording:
            self.abort_task('record')

    # call this to stop acquisition gracefully
    # not thread safe
    def stop_recording(self):
        if self.is_recording:
            self.stop_task('record')

    def get_next_data_elements_to_finish(self, timeout=None):
        new_data_event = threading.Event()
        new_data_elements = list()

        def receive_new_data_elements(data_elements):
            new_data_elements[:] = data_elements
            new_data_event.set()

        def abort():
            new_data_event.set()

        with contextlib.closing(self.data_elements_available_event.listen(receive_new_data_elements)):
            with contextlib.closing(self.abort_event.listen(abort)):
                # wait for the current frame to finish
                if not new_data_event.wait(timeout):
                    raise Exception("Could not start data_source " + str(self.hardware_source_id))

                return new_data_elements

    def get_next_data_elements_to_start(self, timeout=None):
        new_data_event = threading.Event()
        new_data_elements = list()

        def receive_new_data_elements(data_elements):
            new_data_elements[:] = data_elements
            new_data_event.set()

        def abort():
            new_data_event.set()

        with contextlib.closing(self.data_elements_available_event.listen(receive_new_data_elements)):
            with contextlib.closing(self.abort_event.listen(abort)):
                # wait for the current frame to finish
                if not new_data_event.wait(timeout):
                    raise Exception("Could not start data_source " + str(self.hardware_source_id))

                new_data_event.clear()

                if len(new_data_elements) > 0:
                    new_data_event.wait(timeout)

                return new_data_elements

    @contextlib.contextmanager
    def get_data_element_generator(self, sync=True, timeout=None):
        """
            Return a generator for data elements.

            The sync parameter is used to guarantee that the frame returned is started after the generator call.

            NOTE: data elements may return the same ndarray (with different data) each time it is called.
            Callers should handle appropriately.
        """

        def get_data_element():
            if sync:
                return self.get_next_data_elements_to_start(timeout)[0]
            else:
                return self.get_next_data_elements_to_finish(timeout)[0]

        yield get_data_element

    def get_property(self, name):
        return getattr(self, name)

    def set_property(self, name, value):
        setattr(self, name, value)

    def get_api(self, version):
        actual_version = "1.0.0"
        if Utility.compare_versions(version, actual_version) > 0:
            raise NotImplementedError("Hardware Source API requested version %s is greater than %s." % (version, actual_version))

        class HardwareSourceFacade:
            def __init__(self):
                pass

        return HardwareSourceFacade()


def get_data_element_generator_by_id(hardware_source_id, sync=True, timeout=None):
    hardware_source = HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id)
    return hardware_source.get_data_element_generator(sync, timeout)


@contextlib.contextmanager
def get_data_generator_by_id(hardware_source_id, sync=True):
    """
        Return a generator for data.

        :param bool sync: whether to wait for current frame to finish then collect next frame

        NOTE: a new ndarray is created for each call.
    """
    with get_data_element_generator_by_id(hardware_source_id, sync) as data_element_generator:
        def get_last_data():
            return data_element_generator()["data"].copy()
        # error handling not necessary here - occurs above with get_data_element_generator_by_id function
        yield get_last_data


def convert_data_and_metadata_to_data_element(data_and_calibration):
    data_element = dict()
    data_element["data"] = data_and_calibration.data
    if data_and_calibration.dimensional_calibrations:
        spatial_calibrations = list()
        for dimensional_calibration in data_and_calibration.dimensional_calibrations:
            spatial_calibrations.append(dimensional_calibration.write_dict())
        data_element["spatial_calibrations"] = spatial_calibrations
    if data_and_calibration.intensity_calibration:
        intensity_calibration = data_and_calibration.intensity_calibration
        data_element["intensity_calibration"] = intensity_calibration.write_dict()
    # properties (general tags)
    properties = data_and_calibration.metadata.get("hardware_source", dict())
    data_element["properties"] = properties
    return data_element

def convert_data_element_to_data_and_metadata(data_element):
    data = data_element["data"]
    data_shape_and_dtype = data.shape, data.dtype
    dimensional_shape = Image.dimensional_shape_from_shape_and_dtype(*data_shape_and_dtype)
    # dimensional calibrations
    dimensional_calibrations = list()
    if "spatial_calibrations" in data_element:
        spatial_calibrations = data_element.get("spatial_calibrations")
        for dimension, spatial_calibration in enumerate(spatial_calibrations):
            offset = float(spatial_calibration.get("offset", 0.0))
            scale = float(spatial_calibration.get("scale", 1.0))
            units = Unicode.u(spatial_calibration.get("units", ""))
            if scale != 0.0:
                dimensional_calibrations.append(Calibration.Calibration(offset, scale, units))
            else:
                dimensional_calibrations.append(Calibration.Calibration())
    while len(dimensional_calibrations) < len(dimensional_shape):
        dimensional_calibrations.append(Calibration.Calibration())
    while len(dimensional_calibrations) > len(dimensional_shape):
        dimensional_calibrations.pop()
    intensity_calibration = Calibration.Calibration()
    if "intensity_calibration" in data_element:
        intensity_calibration_dict = data_element.get("intensity_calibration")
        offset = float(intensity_calibration_dict.get("offset", 0.0))
        scale = float(intensity_calibration_dict.get("scale", 1.0))
        units = Unicode.u(intensity_calibration_dict.get("units", ""))
        if scale != 0.0:
            intensity_calibration = Calibration.Calibration(offset, scale, units)
    # properties (general tags)
    metadata = None
    if "properties" in data_element:
        metadata = dict()
        hardware_source_metadata = metadata.setdefault("hardware_source", dict())
        hardware_source_metadata.update(Utility.clean_dict(data_element.get("properties")))
    timestamp = datetime.datetime.utcnow()
    return DataAndMetadata.DataAndMetadata(lambda: data.copy(), data_shape_and_dtype, intensity_calibration,
                                           dimensional_calibrations, metadata, timestamp)


@contextlib.contextmanager
def get_data_and_metadata_generator_by_id(hardware_source_id, sync=True):
    with get_data_element_generator_by_id(hardware_source_id, sync) as data_element_generator:
        def get_last_data():
            data_element = data_element_generator()
            return convert_data_element_to_data_and_metadata(data_element)
        # error handling not necessary here - occurs above with get_data_element_generator_by_id function
        yield get_last_data


@contextlib.contextmanager
def get_data_and_metadata_generator_by_id(hardware_source_id, sync=True):
    with get_data_element_generator_by_id(hardware_source_id, sync) as data_element_generator:
        def get_last_data():
            data_element = data_element_generator()
            data = data_element["data"]
            data_shape_and_dtype = data.shape, data.dtype
            # dimensional calibrations
            dimensional_calibrations = None
            if "spatial_calibrations" in data_element:
                spatial_calibrations = data_element.get("spatial_calibrations")
                dimensional_calibrations = list()
                for dimension, spatial_calibration in enumerate(spatial_calibrations):
                    offset = float(spatial_calibration.get("offset", 0.0))
                    scale = float(spatial_calibration.get("scale", 1.0))
                    units = Unicode.u(spatial_calibration.get("units", ""))
                    if scale != 0.0:
                        dimensional_calibrations.append(Calibration.Calibration(offset, scale, units))
            intensity_calibration = None
            if "intensity_calibration" in data_element:
                intensity_calibration_dict = data_element.get("intensity_calibration")
                offset = float(intensity_calibration_dict.get("offset", 0.0))
                scale = float(intensity_calibration_dict.get("scale", 1.0))
                units = Unicode.u(intensity_calibration_dict.get("units", ""))
                if scale != 0.0:
                    intensity_calibration = Calibration.Calibration(offset, scale, units)
            # properties (general tags)
            metadata = None
            if "properties" in data_element:
                metadata = dict()
                hardware_source_metadata = metadata.setdefault("hardware_source", dict())
                hardware_source_metadata.update(Utility.clean_dict(data_element.get("properties")))
            timestamp = datetime.datetime.utcnow()
            return DataAndMetadata.DataAndMetadata(lambda: data.copy(), data_shape_and_dtype, intensity_calibration,
                                                      dimensional_calibrations, metadata, timestamp)
        # error handling not necessary here - occurs above with get_data_element_generator_by_id function
        yield get_last_data


@contextlib.contextmanager
def get_data_item_generator_by_id(hardware_source_id, sync=True):
    """
        Return a generator for data item.

        :param bool sync: whether to wait for current frame to finish then collect next frame

        NOTE: a new data item is created for each call.
    """
    with get_data_element_generator_by_id(hardware_source_id, sync) as data_element_generator:
        def get_last_data_item():
            return ImportExportManager.create_data_item_from_data_element(data_element_generator())
        yield get_last_data_item


def parse_hardware_aliases_config_file(config_path):
    """
        Parse config file for aliases and automatically register them.

        Returns True if alias file was found and parsed (successfully or unsuccessfully).

        Returns False if alias file was not found.

        Config file is a standard .ini file with a section
    """
    if os.path.exists(config_path):
        logging.info("Parsing alias file {:s}".format(config_path))
        try:
            config = configparser.SafeConfigParser()
            config.read(config_path)
            for section in config.sections():
                device = config.get(section, "device")
                hardware_alias = config.get(section, "hardware_alias")
                display_name = config.get(section, "display_name")
                try:
                    logging.info("Adding alias {:s} for device {:s}, display name: {:s} ".format(hardware_alias, device, display_name))
                    HardwareSourceManager().make_instrument_alias(device, hardware_alias, _(display_name))
                except Exception as e:
                    logging.info("Error creating hardware alias {:s} for device {:s} ".format(hardware_alias, device))
                    logging.info(traceback.format_exc())
        except Exception as e:
            logging.info("Error reading alias file from: " + config_path)
            logging.info(traceback.format_exc())
        return True
    return False


def matches_hardware_source(hardware_source_id, channel_id, data_item):
    buffered_data_source = data_item.maybe_data_source
    if buffered_data_source and buffered_data_source.computation is None:
        hardware_source_metadata = buffered_data_source.metadata.get("hardware_source", dict())
        data_item_hardware_source_id = hardware_source_metadata.get("hardware_source_id")
        data_item_channel_id = hardware_source_metadata.get("channel_id")
        return data_item.category == "temporary" and hardware_source_id == data_item_hardware_source_id and channel_id == data_item_channel_id
    return False


def make_hardware_source_filter(document_model, hardware_source_id: str, channel_id: str=None, source_binding: DataItemsBinding.AbstractDataItemsBinding=None) -> DataItemsBinding.DataItemsInContainerBinding:
    filtered_data_items_binding = DataItemsBinding.DataItemsFilterBinding(source_binding) if source_binding else DataItemsBinding.DataItemsInContainerBinding()
    filtered_data_items_binding.container = document_model
    filtered_data_items_binding.sort_key = DataItem.sort_by_date_key
    filtered_data_items_binding.sort_reverse = True
    filtered_data_items_binding.filter = functools.partial(matches_hardware_source, hardware_source_id, channel_id)
    return filtered_data_items_binding