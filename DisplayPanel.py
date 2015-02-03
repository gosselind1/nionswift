# standard libraries
import copy
import datetime
import gettext
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Decorators
from nion.swift import Panel
from nion.swift import ImageCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import Operation
from nion.ui import CanvasItem
from nion.ui import Geometry
from nion.ui import Observable

_ = gettext.gettext


# coordinate systems:
#   widget (origin top left, size of the widget)
#   image_norm ((0,0), (1,1))
#   image_pixel (0,0 size of the image in pixels)
#   calibrated


# how sizing works:
#   the canvas is initially set to fit to the space, meaning all of it is visible
#   when the user presses the fit, fill, or 1:1 buttons, the canvas is resized to match that choice
#   when the window is resized, a best attempt is made to keep the view roughly the same. this may
#     be impossible when the shape of the view changes radically.
#   when the user zooms in/out, the canvas is made larger or smaller by the appropriate amount.

# how to make sure it works:
#   if the new view default is 'fill' or '1:1', do the scroll bars come up in the center?
#   for new view, does zoom go into the center point?
#   switch to 'fit', does zoom still go into center point?


# refer to Illustrator / Default keyboard shortcuts
# http://help.adobe.com/en_US/illustrator/cs/using/WS714a382cdf7d304e7e07d0100196cbc5f-6426a.html
# secondary Lightroom:
# http://helpx.adobe.com/lightroom/help/keyboard-shortcuts.html

# KEYS FOR CHOOSING TOOLS               ACTION/KEY
# selection tool (whole object)         v
# direct selection tool (parts)         a
# line tool                             \
# rectangle tool                        m
# ellipse tool                          l
# rotate tool                           r
# scale tool                            s
# hand tool (moving image)              h
# zoom tool (zooming image)             z

# KEYS FOR VIEWING IMAGES               ACTION/KEY
# fit image to area                     double w/ hand tool
# magnify to 100%                       double w/ zoom tool
# fit image to area                     0
# fill image to area                    Shift-0
# make image 1:1                        1
# display original image                o

# KEYS FOR DRAWING GRAPHICS             ACTION/KEY
# constrain shape                       shift-drag
# move while dragging                   spacebar-drag
# drag from center                      alt-drag (Windows), option-drag (Mac OS)

# KEYS FOR SELECTING GRAPHICS           ACTION/KEY
# use last used selection tool          ctrl (Windows), command (Mac OS)
# add/subtract from selection           alt (Windows), option (Mac OS)

# KEYS FOR MOVING SELECTION/IMAGE       ACTION/KEY
# move in small increments              arrow keys
# move in 10x increments                shift- arrow keys

# KEYS FOR USING PANELS                 ACTION/KEY
# hide all panels                       tab
# hide all panels except data panel     shift-tab

# FUNCTION KEYS                         ACTION/KEY
# tbd


class DisplayPanelOverlayCanvasItem(CanvasItem.AbstractCanvasItem):
    """
        An overlay for image panels to draw and handle focus, selection, and drop targets.

        The overlay has a focused property, but this is not the same as the canvas focused_item.
        The focused property here is just a flag to indicate whether to draw the focus ring.
    """

    def __init__(self, display_panel):
        super(DisplayPanelOverlayCanvasItem, self).__init__()
        self.wants_drag_events = True
        self.display_panel = display_panel
        self.__dropping = False
        self.__drop_region = "none"
        self.__focused = False
        self.__selected = False
        self.__selected_style = "#CCC"  # TODO: platform dependent
        self.__focused_style = "#3876D6"  # TODO: platform dependent

    def close(self):
        self.display_panel = None
        super(DisplayPanelOverlayCanvasItem, self).close()

    def __get_focused(self):
        return self.__focused

    def __set_focused(self, focused):
        if self.__focused != focused:
            self.__focused = focused
            self.update()

    focused = property(__get_focused, __set_focused)

    def __get_selected(self):
        return self.__selected

    def __set_selected(self, selected):
        if self.__selected != selected:
            self.__selected = selected
            self.update()

    selected = property(__get_selected, __set_selected)

    def __set_drop_region(self, drop_region):
        if self.__drop_region != drop_region:
            self.__drop_region = drop_region
            self.update()

    def _repaint(self, drawing_context):

        super(DisplayPanelOverlayCanvasItem, self)._repaint(drawing_context)

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        if self.__drop_region != "none":

            drawing_context.save()

            drawing_context.begin_path()
            if self.__drop_region == "left":
                drawing_context.rect(0, 0, int(canvas_width * 0.10), canvas_height)
            elif self.__drop_region == "right":
                drawing_context.rect(int(canvas_width * 0.90), 0, int(canvas_width - canvas_width * 0.90), canvas_height)
            elif self.__drop_region == "top":
                drawing_context.rect(0, 0, canvas_width, int(canvas_height * 0.10))
            elif self.__drop_region == "bottom":
                drawing_context.rect(0, int(canvas_height * 0.90), canvas_width, int(canvas_height - canvas_height * 0.90))
            else:
                drawing_context.rect(0, 0, canvas_width, canvas_height)
            drawing_context.fill_style = "rgba(255, 0, 0, 0.10)"
            drawing_context.fill()

            drawing_context.restore()

        if self.selected:

            stroke_style = self.__focused_style if self.focused else self.__selected_style

            drawing_context.save()

            drawing_context.begin_path()
            drawing_context.rect(2, 2, canvas_width - 4, canvas_height - 4)
            drawing_context.line_join = "miter"
            drawing_context.stroke_style = stroke_style
            drawing_context.line_width = 4.0
            drawing_context.stroke()

            drawing_context.restore()

    def drag_enter(self, mime_data):
        self.__dropping = True
        self.__set_drop_region("none")
        if self.display_panel:
            return self.display_panel.handle_drag_enter(mime_data)
        return "ignore"

    def drag_leave(self):
        self.__dropping = False
        self.__set_drop_region("none")
        if self.display_panel:
            self.display_panel.handle_drag_leave()
        return False

    def drag_move(self, mime_data, x, y):
        if self.display_panel:
            result = self.display_panel.handle_drag_move(mime_data, x, y)
            if result != "ignore":
                canvas_size = Geometry.IntSize.make(self.canvas_size)
                if x < int(canvas_size.width * 0.10):
                    self.__set_drop_region("left")
                elif x > int(canvas_size.width * 0.90):
                    self.__set_drop_region("right")
                elif y < int(canvas_size.height * 0.10):
                    self.__set_drop_region("top")
                elif y > int(canvas_size.height * 0.90):
                    self.__set_drop_region("bottom")
                else:
                    self.__set_drop_region("middle")
                return result
        self.__set_drop_region("none")
        return "ignore"

    def drop(self, mime_data, x, y):
        drop_region = self.__drop_region
        self.__dropping = False
        self.__set_drop_region("none")
        if self.display_panel:
            return self.display_panel.handle_drop(mime_data, drop_region, x, y)
        return "ignore"


class BrowserDisplayPanelController(object):
    """
        Represents a controller for the content of an image panel.

        Image panels have the ability to update their content spontaneously in response to
        external events such as a selection in another panel changing, acquisition starting,
        and more.
    """
    def __init__(self, display_panel):
        self.type = "browser"
        self.__display_panel = display_panel
        self.__display_panel.document_controller.add_listener(self)
        self.__display_panel.header_canvas_item.end_header_color = "#996633"
        self.browser_data_item_changed(self.__display_panel.document_controller.browser_data_item)

    def close(self):
        self.__display_panel.header_canvas_item.reset_header_colors()
        self.__display_panel.document_controller.remove_listener(self)
        self.__display_panel = None

    @classmethod
    def make(cls, display_panel, d):
        return BrowserDisplayPanelController(display_panel)

    @classmethod
    def detect(cls, display_panel, display_specifier):
        return None

    def save(self, d):
        pass

    def browser_data_item_changed(self, data_item):
        self.__display_panel.set_displayed_data_item(data_item)


class DisplayPanel(object):

    def __init__(self, document_controller):

        self.document_controller = document_controller
        self.ui = document_controller.ui

        self.__weak_workspace = None

        self.__display_specifier = DataItem.DisplaySpecifier()

        class ContentCanvasItem(CanvasItem.CanvasItemComposition):

            def __init__(self, display_panel):
                super(ContentCanvasItem, self).__init__()
                self.display_panel = display_panel

            def close(self):
                self.display_panel = None
                super(ContentCanvasItem, self).close()

            def key_pressed(self, key):
                if self.display_panel.display_canvas_item:
                    return self.display_panel.display_canvas_item.key_pressed(key)
                return super(ContentCanvasItem, self).key_pressed(key)

        self.__content_canvas_item = ContentCanvasItem(self)
        self.__content_canvas_item.wants_mouse_events = True  # only when display_canvas_item is None
        self.__content_canvas_item.focusable = True
        self.__content_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.__overlay_canvas_item = DisplayPanelOverlayCanvasItem(self)
        self.__content_canvas_item.add_canvas_item(self.__overlay_canvas_item)
        self.__header_canvas_item = Panel.HeaderCanvasItem(display_drag_control=True, display_sync_control=True, display_close_control=True)
        self.__header_canvas_item.on_drag_pressed = lambda: self.__begin_drag()
        self.__header_canvas_item.on_sync_clicked = lambda: self.__sync_data_item()
        self.__header_canvas_item.on_close_clicked = lambda: self.__close_display_panel()
        self.__footer_canvas_item = CanvasItem.CanvasItemComposition()
        self.__footer_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__footer_canvas_item.sizing.collapsible = True

        self.canvas_item = CanvasItem.CanvasItemComposition()
        self.canvas_item.layout = CanvasItem.CanvasItemColumnLayout()

        self.canvas_item.add_canvas_item(self.__header_canvas_item)
        self.canvas_item.add_canvas_item(self.__content_canvas_item)
        self.canvas_item.add_canvas_item(self.__footer_canvas_item)

        self.document_controller.register_display_panel(self)

        # this results in data_item_deleted messages
        self.document_controller.document_model.add_listener(self)

        self.__display_panel_controller = None

        self.display_canvas_item = None
        self.__display_type = None

    def close(self):
        # self.canvas_item.close()  # the creator of the image panel is responsible for closing the canvas item
        self.canvas_item = None
        if self.display_canvas_item:
            self.display_canvas_item.about_to_close()
            self.display_canvas_item = None
        self.__content_canvas_item.on_focus_changed = None  # only necessary during tests
        if self.__display_panel_controller:
            self.__display_panel_controller.close()
            self.__display_panel_controller = None
        self.document_controller.document_model.remove_listener(self)
        self.document_controller.unregister_display_panel(self)
        self.__set_display(DataItem.DisplaySpecifier())  # required before destructing display thread
        # release references
        self.workspace_controller = None
        self.__content_canvas_item = None
        self.__overlay_canvas_item = None
        self.__header_canvas_item = None

    @property
    def workspace(self):
        return self.__weak_workspace() if self.__weak_workspace else None

    @workspace.setter
    def workspace(self, workspace):
        self.__weak_workspace = weakref.ref(workspace) if workspace else None

    @property
    def header_canvas_item(self):
        return self.__header_canvas_item

    @property
    def footer_canvas_item(self):
        return self.__footer_canvas_item

    # tasks can be added in two ways, queued or added
    # queued tasks are guaranteed to be executed in the order queued.
    # added tasks are only executed if not replaced before execution.
    # added tasks do not guarantee execution order or execution at all.

    def add_task(self, key, task):
        self.document_controller.add_task(key + str(id(self)), task)

    def clear_task(self, key):
        self.document_controller.clear_task(key + str(id(self)))

    def queue_task(self, task):
        self.document_controller.queue_task(task)

    # save and restore the contents of the image panel

    def save_contents(self, d):
        if self.__display_panel_controller:
            d["controller_type"] = self.__display_panel_controller.type
            self.__display_panel_controller.save(d)
        else:
            data_item = self.display_specifier.data_item
            if data_item:
                d["data_item_uuid"] = str(data_item.uuid)

    def restore_contents(self, d):
        controller_type = d.get("controller_type")
        self.__display_panel_controller = DisplayPanelManager().make_display_panel_controller(controller_type, self, d)
        if not self.__display_panel_controller:
            data_item_uuid_str = d.get("data_item_uuid")
            if data_item_uuid_str:
                data_item = self.document_controller.document_model.get_data_item_by_uuid(uuid.UUID(data_item_uuid_str))
                if data_item:
                    self.set_displayed_data_item(data_item)

    # handle selection. selection means that the image panel is the most recent
    # item to have focus within the workspace, although it can be selected without
    # having focus. this can happen, for instance, when the user switches focus
    # to the data panel.

    def set_selected(self, selected):
        if self.__overlay_canvas_item:  # may be closed
            self.__overlay_canvas_item.selected = selected

    def _is_selected(self):
        """ Used for testing. """
        return self.__overlay_canvas_item.selected

    # this message comes from the canvas items via the on_focus_changed when their focus changes
    def set_focused(self, focused):
        self.__overlay_canvas_item.focused = focused
        if focused:
            self.document_controller.selected_display_panel = self
            self.document_controller.notify_selected_display_specifier_changed(self.display_specifier)

    def _is_focused(self):
        """ Used for testing. """
        return self.__overlay_canvas_item.focused

    @property
    def display_specifier(self):
        """Return the display specifier for the Display in this image panel."""
        return self.__display_specifier

    # sets the data item that this panel displays
    # not thread safe
    def set_displayed_data_item_and_display(self, display_specifier):
        self.__set_display(display_specifier)

    # set the default display for the data item. just a simpler method to call.
    def set_displayed_data_item(self, data_item):
        self.set_displayed_data_item_and_display(DataItem.DisplaySpecifier.from_data_item(data_item))

    def replace_displayed_data_item_and_display(self, display_specifier):
        """
        Replace the displayed data item. This method differs from set_display_data_item
        in that it will recognize when it is receiving a live acquisition and automatically
        set up the live image panel controller.
        """
        if self.__display_panel_controller:
            self.__display_panel_controller.close()
            self.__display_panel_controller = None
        self.__display_panel_controller = DisplayPanelManager().detect_display_panel_controller(self, display_specifier)
        self.set_displayed_data_item_and_display(display_specifier)

    @property
    def buffered_data_source(self):
        return self.__display_specifier.buffered_data_source

    @property
    def display(self):
        return self.__display_specifier.display

    # not thread safe
    def __set_display(self, display_specifier):
        if display_specifier.buffered_data_source:
            assert isinstance(display_specifier.buffered_data_source, DataItem.BufferedDataSource)
            # keep new data in memory. if new and old values are the same, putting
            # this here will prevent the data from unloading and then reloading.
            display_specifier.buffered_data_source.increment_data_ref_count()
        # track data item in this class to report changes
        if self.__display_specifier.buffered_data_source:
            self.__display_specifier.buffered_data_source.decrement_data_ref_count()  # don't keep data in memory anymore
        if self.__display_specifier.display:
            self.__display_specifier.display.remove_listener(self)
        self.__display_specifier = copy.copy(display_specifier)
        # these connections should be configured after the messages above.
        # the instant these are added, we may be receiving messages from threads.
        if self.__display_specifier.display:
            self.__display_specifier.display.add_listener(self)  # for display_changed and display_graphic_selection_changed
        self.__update_display_canvas(self.__display_specifier)

    # this message comes from the document model.
    def data_item_deleted(self, deleted_data_item):
        data_item = self.display_specifier.data_item
        # if our item gets deleted, clear the selection
        if deleted_data_item == data_item:
            self.__set_display(DataItem.DisplaySpecifier())

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def __begin_drag(self):
        if self.__display_specifier.data_item is not None:
            mime_data = self.ui.create_mime_data()
            mime_data.set_data_as_string("text/data_item_uuid", str(self.__display_specifier.data_item.uuid))
            root_canvas_item = self.canvas_item.root_container
            thumbnail_data = self.__display_specifier.display.get_processed_data("thumbnail")
            def drag_finished(action):
                if action == "move" and self.document_controller.replaced_data_item is not None:
                    display_specifier = DataItem.DisplaySpecifier.from_data_item(self.document_controller.replaced_data_item)
                    self.__set_display(display_specifier)
                    self.document_controller.replaced_data_item = None
            root_canvas_item.canvas_widget.drag(mime_data, thumbnail_data, drag_finished_fn=drag_finished)

    def __sync_data_item(self):
        if self.__display_specifier.data_item is not None:
            self.document_controller.select_data_item_in_data_panel(self.__display_specifier.data_item)

    def __close_display_panel(self):
        if len(self.workspace_controller.display_panels) > 1:
            self.workspace_controller.remove_display_panel(self)

    # this message comes from the display associated with this panel.
    # the connection is established in __set_display via display.add_listener.
    # this will be called when anything in the data item changes, including things
    # like graphics or the data itself.
    # thread safe.
    def display_changed(self, display):
        display_specifier = copy.copy(self.__display_specifier)
        if display_specifier.display:
            self.__update_display_canvas(display_specifier)

    def display_graphic_selection_changed(self, display, graphic_selection):
        # this message comes from the display when the graphic selection changes
        display_calibrated_values = display.display_calibrated_values
        data_and_calibration = display.data_and_calibration
        drawn_graphics = display.drawn_graphics
        if self.display_canvas_item:  # may be closed
            self.display_canvas_item.update_regions(data_and_calibration, graphic_selection, drawn_graphics, display_calibrated_values)

    # update the display canvas, etc.
    # clear any pending display update at the end
    # not thread safe
    def __update_display_canvas(self, display_specifier):
        if self.__header_canvas_item:  # may be closed
            self.__header_canvas_item.title = self.document_controller.get_displayed_title_for_data_item(display_specifier.data_item)
        display_type = None
        data_and_calibration = display_specifier.display.data_and_calibration if display_specifier.display else None
        if data_and_calibration:
            if data_and_calibration.is_data_1d:
                display_type = "line_plot"
            elif data_and_calibration.is_data_2d or data_and_calibration.is_data_3d:
                display_type = "image"
        if display_type != self.__display_type:
            if self.display_canvas_item:
                self.__content_canvas_item.remove_canvas_item(self.display_canvas_item)
                self.display_canvas_item = None

            class DisplayCanvasItemDelegate(object):
                def __init__(self, display_panel):
                    self.__display_panel = display_panel

                def add_index_to_selection(self, index):
                    self.__display_panel.display_specifier.display.graphic_selection.add(index)

                def remove_index_from_selection(self, index):
                    self.__display_panel.display_specifier.display.graphic_selection.remove(index)

                def set_selection(self, index):
                    self.__display_panel.display_specifier.display.graphic_selection.set(index)

                def clear_selection(self):
                    self.__display_panel.display_specifier.display.graphic_selection.clear()

                def add_and_select_region(self, region):
                    self.__display_panel.display_specifier.buffered_data_source.add_region(region)  # this will also make a drawn graphic
                    # hack to select it. it will be the last item.
                    self.__display_panel.display_specifier.display.graphic_selection.set(len(self.__display_panel.display_specifier.display.drawn_graphics) - 1)

                def nudge_selected_graphics(self, mapping, delta):
                    display = self.__display_panel.display_specifier.display
                    if display:
                        all_graphics = display.drawn_graphics
                        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if display.graphic_selection.contains(graphic_index)]
                        for graphic in graphics:
                            graphic.nudge(mapping, delta)

                def update_graphics(self, widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers):
                    with self.__display_panel.display_specifier.data_item.data_item_changes():
                        for graphic in graphic_drag_items:
                            index = self.__display_panel.display_specifier.display.drawn_graphics.index(graphic)
                            part_data = (graphic_drag_part, ) + graphic_part_data[index]
                            graphic.adjust_part(widget_mapping, graphic_drag_start_pos, Geometry.IntPoint.make(pos), part_data, modifiers)

                @property
                def tool_mode(self):
                    return self.__display_panel.document_controller.tool_mode

                @tool_mode.setter
                def tool_mode(self, value):
                    self.__display_panel.document_controller.tool_mode = value

                def show_context_menu(self, gx, gy):
                    self.__display_panel.document_controller.show_context_menu_for_data_item(self.__display_panel.document_controller.document_model, self.__display_panel.display_specifier.data_item, gx, gy)

                def begin_mouse_tracking(self):
                    self.__display_panel.document_controller.document_model.begin_data_item_transaction(
                        self.__display_panel.display_specifier.data_item)

                def end_mouse_tracking(self):
                    data_item = self.__display_panel.display_specifier.data_item
                    display = self.__display_panel.display_specifier.display
                    if display:
                        self.__display_panel.document_controller.document_model.end_data_item_transaction(data_item)

                def mouse_clicked(self, image_position, modifiers):
                    return self.__display_panel.image_panel_mouse_clicked(image_position, modifiers)

                def delete_key_pressed(self):
                    if self.__display_panel.document_controller.remove_graphic():
                        return True
                    self.__display_panel.set_displayed_data_item(None)
                    return False

                def key_pressed(self, key):
                    return self.__display_panel.image_panel_key_pressed(key)

                def cursor_changed(self, source, pos, image_size):
                    display = self.__display_panel.display_specifier.display
                    data_and_calibration = display.data_and_calibration if display else None
                    display_calibrated_values = display.display_calibrated_values if display else False
                    self.__display_panel.document_controller.cursor_changed(source, data_and_calibration, display_calibrated_values, pos, image_size)

                def update_display_properties(self, display_properties):
                    for key, value in display_properties.iteritems():
                        setattr(self.__display_panel.display_specifier.display, key, value)

            if display_type == "line_plot":
                self.display_canvas_item = LinePlotCanvasItem.LinePlotCanvasItem(self.ui.get_font_metrics, DisplayCanvasItemDelegate(self))
                self.__content_canvas_item.insert_canvas_item(0, self.display_canvas_item)
            elif display_type == "image":
                self.display_canvas_item = ImageCanvasItem.ImageCanvasItem(DisplayCanvasItemDelegate(self))
                self.__content_canvas_item.insert_canvas_item(0, self.display_canvas_item)
                self.display_canvas_item.set_fit_mode()
            self.__display_type = display_type
            if self.__content_canvas_item:
                self.__content_canvas_item.update()
        display = display_specifier.display
        if display and self.display_canvas_item:  # may be closed
            if display_type == "image":
                data_shape_and_dtype = (display.preview_2d_shape, numpy.uint32)
                intensity_calibration = Calibration.Calibration()
                dimensional_calibrations = [Calibration.Calibration(), Calibration.Calibration()]
                preview_data_and_calibration = Operation.DataAndCalibration(lambda: display.preview_2d,
                                                                            data_shape_and_dtype, intensity_calibration,
                                                                            dimensional_calibrations, dict(),
                                                                            datetime.datetime.utcnow())
                self.display_canvas_item.update_display_state(preview_data_and_calibration)
            elif display_type == "line_plot":
                display_properties = {"y_min": display.y_min, "y_max": display.y_max,
                    "left_channel": display.left_channel, "right_channel": display.right_channel}
                self.display_canvas_item.update_display_state(data_and_calibration, display_properties,
                                                              display.display_calibrated_values)
            self.display_graphic_selection_changed(display_specifier.display,
                                                   display_specifier.display.graphic_selection)
        if self.__content_canvas_item:  # may be closed
            self.__content_canvas_item.wants_mouse_events = self.display_canvas_item is None
        selected = self.document_controller.selected_display_panel == self
        if self.__overlay_canvas_item:  # may be closed
            self.__overlay_canvas_item.selected = display_specifier.display is not None and selected

    # ths message comes from the canvas item via the delegate.
    def image_panel_key_pressed(self, key):
        #logging.debug("text=%s key=%s mod=%s", key.text, hex(key.key), key.modifiers)
        # if key.text == "b" or key.text == "a":
        #     if self.__image_panel_controller:
        #         self.__image_panel_controller.close()
        #         self.__image_panel_controller = None
        #     elif key.text == "a":
        #         self.__image_panel_controller = LiveDisplayPanelController(self)
        #     elif key.text == "b":
        #         self.__image_panel_controller = BrowserDisplayPanelController(self)
        #     return True
        return DisplayPanelManager().key_pressed(self, key)

    def image_panel_mouse_clicked(self, image_position, modifiers):
        DisplayPanelManager().mouse_clicked(self, self.display_specifier, image_position, modifiers)

    def image_panel_get_font_metrics(self, font, text):
        return self.ui.get_font_metrics(font, text)

    def image_panel_get_tool_mode(self):
        return self.document_controller.tool_mode

    def image_panel_set_tool_mode(self, tool_mode):
        self.document_controller.tool_mode = tool_mode

    def image_panel_show_context_menu(self, gx, gy):
        self.document_controller.show_context_menu_for_data_item(self.document_controller.document_model, self.display_specifier.data_item, gx, gy)

    def image_panel_cursor_changed(self, source, display, pos, image_size):
        data_and_calibration = display.data_and_calibration if display else None
        display_calibrated_values = display.display_calibrated_values if display else False
        self.document_controller.cursor_changed(source, data_and_calibration, display_calibrated_values, pos, image_size)

    def image_panel_delete_key_pressed(self):
        if self.document_controller.remove_graphic():
            return True
        self.set_displayed_data_item(None)
        return False

    def handle_drag_enter(self, mime_data):
        if self.workspace_controller:
            return self.workspace_controller.handle_drag_enter(self, mime_data)
        return "ignore"

    def handle_drag_leave(self):
        if self.workspace_controller:
            return self.workspace_controller.handle_drag_leave(self)
        return False

    def handle_drag_move(self, mime_data, x, y):
        if self.workspace_controller:
            return self.workspace_controller.handle_drag_move(self, mime_data, x, y)
        return "ignore"

    def handle_drop(self, mime_data, region, x, y):
        if self.workspace_controller:
            return self.workspace_controller.handle_drop(self, mime_data, region, x, y)
        return "ignore"


# image panel manager acts as a broker for significant events occurring
# regarding image panels. listeners can attach themselves to this object
# and receive messages regarding image panels. for instance, when the user
# presses a key on an image panel that isn't handled directly by the image
# panel, listeners can be advised of this event.
class DisplayPanelManager(Observable.Broadcaster):
    __metaclass__ = Decorators.Singleton

    def __init__(self):
        super(DisplayPanelManager, self).__init__()
        self.__display_panel_controllers = dict()  # maps controller_type to make_fn

    # events from the image panels
    def key_pressed(self, image_panel, key):
        self.notify_listeners("image_panel_key_pressed", image_panel, key)
        return False

    def mouse_clicked(self, image_panel, display_specifier, image_position, modifiers):
        self.notify_listeners("image_panel_mouse_clicked", image_panel, display_specifier, image_position, modifiers)
        return False

    def register_display_panel_controller(self, controller_type, make_fn):
        self.__display_panel_controllers[controller_type] = make_fn

    def unregister_display_panel_controller(self, controller_type):
        del self.__display_panel_controllers[controller_type]

    def make_display_panel_controller(self, controller_type, display_panel, d):
        if controller_type in self.__display_panel_controllers:
            return self.__display_panel_controllers[controller_type].make(display_panel, d)
        return None

    def detect_display_panel_controller(self, display_panel, display_specifier):
        for controller_type in self.__display_panel_controllers:
            display_panel_controller = self.__display_panel_controllers[controller_type].detect(display_panel, display_specifier)
            if display_panel_controller:
                return display_panel_controller
        return None


DisplayPanelManager().register_display_panel_controller("browser", BrowserDisplayPanelController)
