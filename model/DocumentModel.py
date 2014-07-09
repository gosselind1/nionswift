# standard libraries
import collections
import copy
import datetime
import gettext
import logging
import numbers
import os.path
import threading
import uuid
import weakref

# third party libraries
import scipy

# local libraries
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import Image
from nion.swift.model import ImportExportManager
from nion.swift.model import PlugInManager
from nion.swift.model import Storage
from nion.swift.model import Utility

_ = gettext.gettext


class DataItemVault(object):

    """ Vaults should be stateless so that we can switch them in data items without repercussions. """

    def __init__(self, datastore=None, properties=None, reference_type=None, reference=None, storage_dict=None, delegate=None):
        self.datastore = datastore
        self.__properties = copy.deepcopy(properties) if properties else dict()
        self.__properties_lock = threading.RLock()
        self.storage_dict = storage_dict if storage_dict is not None else self.__properties
        self.__delegate = delegate  # a delegate item vault for updating properties
        self.__weak_data_item = None
        # reference type and reference indicate how to save/load data and properties
        self.reference_type = reference_type
        self.reference = reference

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    def __set_data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
    data_item = property(__get_data_item, __set_data_item)

    def __get_delegate(self):
        return self.__delegate
    delegate = property(__get_delegate)

    def __get_properties(self):
        with self.__properties_lock:
            return copy.deepcopy(self.__properties)
    properties = property(__get_properties)

    def __get_properties_lock(self):
        if self.__delegate:
            return self.__delegate.properties_lock
        else:
            return self.__properties_lock
    properties_lock = property(__get_properties_lock)

    def set_properties_low_level(self, uuid_, properties, file_datetime):
        """ Only used to migrate data """
        if self.datastore:
            assert self.reference is not None
            with self.__properties_lock:
                self.__properties = copy.deepcopy(properties)
                self.datastore.set_root_properties(uuid_, self.properties, self.reference, file_datetime)

    def load_data_low_level(self):
        return self.datastore.load_data_reference("master_data", self.reference_type, self.reference)

    def set_value_low_level(self, name, value):
        with self.properties_lock:
            self.storage_dict[name] = value

    def update_properties(self):
        if self.__delegate:
            self.__delegate.update_properties()
        elif self.datastore:
            self.ensure_reference_valid()
            file_datetime = Utility.get_datetime_from_datetime_item(self.data_item.datetime_original)
            self.datastore.set_root_properties(self.data_item.uuid, self.properties, self.reference, file_datetime)

    def insert_item(self, name, before_index, item):
        with self.properties_lock:
            item_list = self.storage_dict.setdefault(name, list())
            item_dict = dict()
            item_list.insert(before_index, item_dict)
            item.vault = DataItemVault(delegate=self, storage_dict=item_dict)
            item.write_storage(DataItemVault(delegate=self, storage_dict=item_dict))
        self.update_properties()

    def remove_item(self, name, index, item):
        with self.properties_lock:
            item_list = self.storage_dict[name]
            del item_list[index]
        self.update_properties()

    def get_default_reference(self):
        uuid_ = self.data_item.uuid
        datetime_item = self.data_item.datetime_original
        session_id = self.data_item.session_id
        # uuid_.bytes.encode('base64').rstrip('=\n').replace('/', '_')
        # and back: uuid_ = uuid.UUID(bytes=(slug + '==').replace('_', '/').decode('base64'))
        # also:
        def encode(uuid_, alphabet):
            result = str()
            uuid_int = uuid_.int
            while uuid_int:
                uuid_int, digit = divmod(uuid_int, len(alphabet))
                result += alphabet[digit]
            return result
        encoded_uuid_str = encode(uuid_, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")  # 25 character results
        datetime_item = datetime_item if datetime_item else Utility.get_current_datetime_item()
        datetime_ = Utility.get_datetime_from_datetime_item(datetime_item)
        datetime_ = datetime_ if datetime_ else datetime.datetime.now()
        path_components = datetime_.strftime("%Y-%m-%d").split('-')
        session_id = session_id if session_id else datetime_.strftime("%Y%m%d-000000")
        path_components.append(session_id)
        path_components.append("data_" + encoded_uuid_str)
        return os.path.join(*path_components)

    def ensure_reference_valid(self):
        if not self.reference:
            self.reference_type = "relative_file"
            self.reference = self.get_default_reference()

    def update_data(self, data_shape, data_dtype, data=None):
        if self.datastore is not None:
            self.ensure_reference_valid()
            file_datetime = Utility.get_datetime_from_datetime_item(self.data_item.datetime_original)
            self.datastore.set_root_data(self.data_item.uuid, data, data_shape, data_dtype, self.reference, file_datetime)

    def load_data(self):
        assert self.data_item.has_master_data
        return self.datastore.load_data_reference("master_data", self.reference_type, self.reference)

    def __can_reload_data(self):
        return self.datastore is not None
    can_reload_data = property(__can_reload_data)

    def set_value(self, name, value):
        with self.properties_lock:
            self.storage_dict[name] = value
        self.update_properties()

    def get_vault_for_item(self, name, index):
        with self.properties_lock:
            storage_dict = self.storage_dict[name][index]
        return DataItemVault(delegate=self, storage_dict=storage_dict)

    def has_value(self, name):
        with self.properties_lock:
            return name in self.storage_dict

    def get_value(self, name):
        with self.properties_lock:
            return self.storage_dict[name]

    def get_item_vaults(self, name):
        if self.has_value(name):
            return [DataItemVault(delegate=self, storage_dict=storage_dict) for storage_dict in self.storage_dict[name]]
        return list()


class DbDataItemVault(object):

    def __init__(self, document_model, datastore, storage_cache):
        self.__weak_document_model = weakref.ref(document_model)
        self.__datastore = datastore
        self.__storage_cache = storage_cache
        self.__data_items = list()

    def __get_data_items(self):
        return self.__data_items
    data_items = property(__get_data_items)

    def read_data_items(self):
        document_model = self.__weak_document_model()
        data_item_tuples = self.__datastore.find_data_item_tuples()
        data_items = list()
        for data_item_uuid, properties, reference_type, reference in data_item_tuples:
            vault = DataItemVault(self.__datastore, properties=properties, reference_type=reference_type, reference=reference)
            current_version = 2
            version = properties.get("version", 0)
            if version == 1:
                if "spatial_calibrations" in properties:
                    properties["intrinsic_spatial_calibrations"] = properties["spatial_calibrations"]
                    del properties["spatial_calibrations"]
                if "intensity_calibration" in properties:
                    properties["intrinsic_intensity_calibration"] = properties["intensity_calibration"]
                    del properties["intensity_calibration"]
                if "data_source_uuid" in properties:
                    # for now, this is not translated into v2. it was an extra item.
                    del properties["data_source_uuid"]
                if "properties" in properties:
                    old_properties = properties["properties"]
                    new_properties = properties.setdefault("hardware_source", dict())
                    new_properties.update(copy.deepcopy(old_properties))
                    if "session_uuid" in new_properties:
                        del new_properties["session_uuid"]
                    del properties["properties"]
                temp_data = vault.load_data_low_level()
                if temp_data is not None:
                    properties["master_data_dtype"] = str(temp_data.dtype)
                    properties["master_data_shape"] = temp_data.shape
                properties["displays"] = [{}]
                properties["uuid"] = str(uuid.uuid4())  # assign a new uuid
                vault.set_value_low_level("version", current_version)
                vault.set_value_low_level("reader_version", current_version)
                vault.set_properties_low_level(data_item_uuid, properties, datetime.datetime.now())
                logging.info("Updated %s", vault.reference)
            data_item = DataItem.DataItem(vault=vault, item_uuid=data_item_uuid, create_display=False)
            assert(len(data_item.displays) > 0)
            data_items.append(data_item)
        def sort_by_date_key(data_item):
            return Utility.get_datetime_from_datetime_item(data_item.datetime_original)
        data_items.sort(key=sort_by_date_key)
        for index, data_item in enumerate(data_items):
            self.__data_items.insert(index, data_item)
            data_item.storage_cache = self.__storage_cache
            data_item.add_listener(document_model)

    def insert(self, before_index, data_item):
        # TODO: move the tail into the caller area
        # this comes from MutableRelationship, StorageBase, and DocumentModel.notify_insert_item
        assert data_item is not None
        assert data_item not in self.__data_items
        assert before_index <= len(self.__data_items) and before_index >= 0
        document_model = self.__weak_document_model()
        # insert in internal list
        self.__data_items.insert(before_index, data_item)
        # keep storage up-to-date. transform from memory vault to new vault.
        # references do not need to be updated since they will be written later.
        data_item.update_vault(DataItemVault(properties=data_item.vault.properties))
        data_item.vault.data_item = data_item
        data_item.vault.datastore = self.__datastore
        self.__datastore.add_root_item_uuid("data-item", data_item.uuid)
        data_item.storage_cache = self.__storage_cache
        data_item.write()
        # be a listener. why?
        data_item.add_listener(document_model)
        document_model.notify_listeners("data_item_inserted", document_model, data_item, before_index, False)

    def remove(self, data_item):
        # TODO: move the tail into the caller area
        # this comes from MutableRelationship, StorageBase, and DocumentModel.notify_remove_item
        assert data_item is not None
        assert data_item in self.__data_items
        document_model = self.__weak_document_model()
        index = self.__data_items.index(data_item)
        # do actual removal
        del self.__data_items[index]
        # keep storage up-to-date
        self.__datastore.remove_root_item_uuid("data-item", data_item.uuid, data_item.vault.reference_type, data_item.vault.reference)
        data_item.update_vault(DataItem.DataItemMemoryVault(properties=data_item.vault.properties))
        #data_item.vault.datastore = None
        data_item.__storage_cache = None
        # unlisten to data item
        data_item.remove_listener(document_model)
        # update data item count
        document_model.notify_listeners("data_item_removed", document_model, data_item, index, False)
        if data_item.get_observer_count(document_model) == 0:  # ugh?
            document_model.notify_listeners("data_item_deleted", data_item)


class ObjectStore(object):

    """
        All objects participating in the document model should register themselves
        with the object store. Other objects can then subscribe and unsubscribe to
        know when a particular object (identified by uuid) becomes available or
        unavailable. This facilitates lazy connections between objects.
    """

    def __init__(self):
        self.__subscriptions = dict()
        self.__objects = dict()

    def register(self, object):
        """
            Register an object with the object store.

            :param object: an object with a uuid property

            Objects will be automatically unregistered when they are garbage
            collected.
        """
        object_uuid = object.uuid
        def remove_object(weak_object):
            object = self.__objects[object_uuid]
            for registered, unregistered in self.__subscriptions.get(object_uuid, list()):
                if unregistered:
                    unregistered(object)
            del self.__objects[object_uuid]
            del self.__subscriptions[object_uuid]
        weak_object = weakref.ref(object, remove_object)
        self.__objects[object_uuid] = weak_object
        for registered, unregistered in self.__subscriptions.get(object_uuid, list()):
            if registered:
                registered(object)

    def subscribe(self, uuid_, registered, unregistered):
        """
            Subscribe to a particular object being registered or unregistered.

            :param uuid_: the uuid of the object to subscribe to
            :param registered: a function taking one parameter (the object) to be called when the object gets registered
            :param unregistered: a function taking one parameter (the object) to be called when the object gets unregistered

            If the object is already registered, registered will be invoked immediately.
        """
        self.__subscriptions.setdefault(uuid_, list()).append((registered, unregistered))
        weak_object = self.__objects.get(uuid_)
        object = weak_object and weak_object()
        if object is not None:
            registered(object)


class DocumentModel(Storage.StorageBase):

    def __init__(self, datastore, storage_cache=None):
        super(DocumentModel, self).__init__()
        self.object_store = ObjectStore()
        self.datastore = datastore
        self.storage_cache = storage_cache if storage_cache else Storage.DictStorageCache()
        self.__data_item_vault = DbDataItemVault(self, datastore, self.storage_cache)
        self.storage_relationships += ["data_groups"]
        self.storage_type = "document"
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.session_id = None
        self.start_new_session()
        if self.datastore.initialized:
            self.__read()
        else:
            self.datastore.set_root(self)
            self.write()

    def __del__(self):
        self.datastore.disconnected = True

    def __read(self):
        # first read the items
        parent_node, uuid = self.datastore.find_root_node("document")
        self._set_uuid(uuid)
        data_groups = self.datastore.get_items(parent_node, "data_groups")
        self.__data_item_vault.read_data_items()
        # now update the fields on self, disconnecting the datastore
        # to prevent writing them back out to the database.
        self.datastore.disconnected = True
        for data_item in self.__data_item_vault.data_items:
            data_item.connect_data_sources(self.get_data_item_by_uuid)
            data_item.object_store = self.object_store
        for data_group in data_groups:
            self.append_data_group(data_group)
        for data_group in self.data_groups:
            data_group.connect_data_items(self.get_data_item_by_uuid)
        self.datastore.disconnected = False

    def close(self):
        """ Optional method to close the document model. """
        for data_item in self.data_items:
            data_item.close()

    def start_new_session(self):
        self.session_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    def append_data_item(self, data_item):
        self.insert_data_item(len(self.data_items), data_item)

    def insert_data_item(self, before_index, data_item):
        self.__data_item_vault.insert(before_index, data_item)
        data_item.connect_data_sources(self.get_data_item_by_uuid)
        data_item.object_store = self.object_store

    def remove_data_item(self, data_item):
        # remove the data item from any groups
        for data_group in self.get_flat_data_group_generator():
            if data_item in data_group.data_items:
                data_group.remove_data_item(data_item)
        # remove data items that are entirely dependent on data item being removed
        for other_data_item in copy.copy(self.data_items):
            if other_data_item.data_source == data_item:
                self.remove_data_item(other_data_item)
        # tell the data item it is about to be removed
        data_item.about_to_be_removed()
        # disconnect the data source
        data_item.object_store = None
        data_item.disconnect_data_sources()
        # remove it from the vault
        self.__data_item_vault.remove(data_item)

    def __get_data_items(self):
        return tuple(self.__data_item_vault.data_items)
    data_items = property(__get_data_items)

    def get_dependent_data_items(self, parent_data_item):
        return [data_item for data_item in self.data_items if data_item.data_source == parent_data_item]

    def append_data_group(self, data_group):
        self.insert_data_group(len(self.data_groups), data_group)

    def insert_data_group(self, before_index, data_group):
        self.data_groups.insert(before_index, data_group)

    def remove_data_group(self, data_group):
        data_group.disconnect_data_items()
        self.data_groups.remove(data_group)

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("My Data")
            self.append_data_group(data_group)

    def create_sample_images(self, resources_path):
        if True:
            data_group = self.get_or_create_data_group(_("Example Data"))
            handler = ImportExportManager.NDataImportExportHandler(None, ["ndata1"])
            samples_dir = os.path.join(resources_path, "SampleImages")
            #logging.debug("Looking in %s", samples_dir)
            def is_ndata(file_path):
                #logging.debug("Checking %s", file_path)
                _, extension = os.path.splitext(file_path)
                return extension == ".ndata1"
            if os.path.isdir(samples_dir):
                sample_paths = [os.path.normpath(os.path.join(samples_dir, d)) for d in os.listdir(samples_dir) if is_ndata(os.path.join(samples_dir, d))]
            else:
                sample_paths = []
            for sample_path in sorted(sample_paths):
                def source_file_path_in_document(sample_path_):
                    for member_data_item in self.data_items:
                        if os.path.normpath(member_data_item.source_file_path) == sample_path_:
                            return True
                    return False
                if not source_file_path_in_document(sample_path):
                    data_items = handler.read_data_items(None, "ndata1", sample_path)
                    for data_item in data_items:
                        #__, file_name = os.path.split(sample_path)
                        #title, __ = os.path.splitext(file_name)
                        #data_item.title = title
                        self.append_data_item(data_item)
                        data_group.append_data_item(data_item)
        else:
            # for testing, add a checkerboard image data item
            checkerboard_image_source = DataItem.DataItem()
            checkerboard_image_source.title = "Checkerboard"
            with checkerboard_image_source.data_ref() as data_ref:
                data_ref.master_data = Image.create_checkerboard((512, 512))
            self.append_data_item(checkerboard_image_source)
            # for testing, add a color image data item
            color_image_source = DataItem.DataItem()
            color_image_source.title = "Green Color"
            with color_image_source.data_ref() as data_ref:
                data_ref.master_data = Image.create_color_image((512, 512), 128, 255, 128)
            self.append_data_item(color_image_source)
            # for testing, add a color image data item
            lena_image_source = DataItem.DataItem()
            lena_image_source.title = "Lena"
            with lena_image_source.data_ref() as data_ref:
                data_ref.master_data = scipy.misc.lena()
            self.append_data_item(lena_image_source)

    # this message comes from a data item when it wants to be removed from the document. ugh.
    def request_remove_data_item(self, data_item):
        DataGroup.get_data_item_container(self, data_item).remove_data_item(data_item)

    # TODO: what about thread safety for these classes?

    class _DataAccessorIter(object):
        def __init__(self, iter):
            self.iter = iter
        def __iter__(self):
            return self
        def next(self):
            data_item = self.iter.next()
            if data_item:
                with data_item.data_ref() as data_ref:
                    return data_ref.data
            return None

    class DataAccessor(object):
        def __init__(self, document_model):
            self.__document_model_weakref = weakref.ref(document_model)
        def __get_document_model(self):
            return self.__document_model_weakref()
        document_model = property(__get_document_model)
        # access by bracket notation
        def __len__(self):
            return self.document_model.get_data_item_count()
        def __getitem__(self, key):
            data = self.document_model.get_data_by_key(key)
            if data is None:
                raise KeyError
            return data
        def __setitem__(self, key, value):
            return self.document_model.set_data_by_key(key, value)
        def __delitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item:
                self.document_model.remove_data_item(data_item)
        def __iter__(self):
            return DocumentModel._DataAccessorIter(self.document_model.get_flat_data_item_generator())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_model.data_items_by_key]
        def title_keys(self):
            return [data_item.title for data_item in self.document_model.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    class DataItemAccessor(object):
        def __init__(self, document_model):
            self.__document_model_weakref = weakref.ref(document_model)
        def __get_document_model(self):
            return self.__document_model_weakref()
        document_model = property(__get_document_model)
        # access by bracket notation
        def __len__(self):
            return self.document_model.get_data_item_count()
        def __getitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item is None:
                raise KeyError
            return data_item
        def __delitem__(self, key):
            data_item = self.document_model.get_data_item_by_key(key)
            if data_item:
                self.document_model.remove_data_item(data_item)
        def __iter__(self):
            return iter(self.document_model.get_flat_data_item_generator())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_model.data_items_by_key]
        def title_keys(self):
            return [data_item.title for data_item in self.document_model.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    # Return a generator over all data items
    def get_flat_data_item_generator(self):
        for data_item in self.data_items:
            yield data_item

    # Return a generator over all data groups
    def get_flat_data_group_generator(self):
        return DataGroup.get_flat_data_group_generator_in_container(self)

    def get_data_group_by_uuid(self, uuid):
        for data_group in DataGroup.get_flat_data_group_generator_in_container(self):
            if data_group.uuid == uuid:
                return data_group
        return None

    def get_data_item_count(self):
        return len(list(self.get_flat_data_item_generator()))

    # temporary method to find the container of a data item. this goes away when
    # data items get stored in a flat table.
    def get_data_item_data_group(self, data_item):
        for data_group in self.get_flat_data_group_generator():
            if data_item in DataGroup.get_flat_data_item_generator_in_container(data_group):
                return data_group
        return None

    # access data item by key (title, uuid, index)
    def get_data_item_by_key(self, key):
        if isinstance(key, numbers.Integral):
            return list(self.get_flat_data_item_generator())[key]
        if isinstance(key, uuid.UUID):
            return self.get_data_item_by_uuid(key)
        return self.get_data_item_by_title(str(key))
    def get_data_by_key(self, key):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None
    def set_data_by_key(self, key, data):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            if isinstance(key, numbers.Integral):
                raise IndexError
            if isinstance(key, uuid.UUID):
                raise KeyError
            data_item = DataItem.DataItem()
            data_item.title = str(key)
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
            self.append_data_item(data_item)
        return data_item

    # access data items by title
    def get_data_item_by_title(self, title):
        for data_item in self.get_flat_data_item_generator():
            if data_item.title == title:
                return data_item
        return None
    def get_data_by_title(self, title):
        data_item = self.get_data_item_by_title(title)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None

    # access data items by index
    def get_data_item_by_index(self, index):
        return list(self.get_flat_data_item_generator())[index]
    def get_data_by_index(self, index):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None
    def set_data_by_index(self, index, data):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            raise IndexError
    def get_index_for_data_item(self, data_item):
        return list(self.get_flat_data_item_generator()).index(data_item)

    # access data items by uuid
    def get_data_item_by_uuid(self, uuid):
        for data_item in self.get_flat_data_item_generator():
            if data_item.uuid == uuid:
                return data_item
        return None
    def get_data_by_uuid(self, uuid):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            with data_item.data_ref() as data_ref:
                return data_ref.data
        return None
    def set_data_by_uuid(self, uuid, data):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            with data_item.data_ref() as data_ref:
                data_ref.master_data = data
        else:
            raise KeyError

    def get_or_create_data_group(self, group_name):
        data_group = DataGroup.get_data_group_in_container_by_title(self, group_name)
        if data_group is None:
            # we create a new group
            data_group = DataGroup.DataGroup()
            data_group.title = group_name
            self.insert_data_group(0, data_group)
        return data_group
