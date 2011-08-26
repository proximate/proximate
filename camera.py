#
# Proximate - Peer-to-peer social networking
#
# Copyright (c) 2008-2011 Nokia Corporation
#
# All rights reserved.
#
# This software is licensed under The Clear BSD license.
# See the LICENSE file for more details.
#
# Using Python GStreamer to control the camera

camerasupport = True
try:
    import gst
except ImportError:
    camerasupport = False

from support import warning, info, debug
from proximateprotocol import PLUGIN_TYPE_NOTIFICATION
from plugins import get_plugin_by_type

class Camera_Exception(Exception):
    # This class is an exception used in Camera_Plugin.
    # Nothing is defined cause this will only serve as a way
    # to tranfer result of an if statement across functions.
    pass

# If no resolution is given, the default one will be used
DEFAULT_RESOLUTION = (352,288)

class Camera:
    """ The Camera plugin controls the tablets camera.
        At the moment it can only take a snapshot with it's take_photo function.
    """

    def __init__(self, resolution=DEFAULT_RESOLUTION, overlay=None):
        if not camerasupport:
            raise Camera_Exception

        self.buffer_cb_id = 0
        self.width, self.height = resolution
        self.overlay = overlay
        self.buffer = None
        if overlay:
            overlay.connect('expose-event', self.expose_cb)
        try:
            self.init_pipeline()
        except gst.ElementNotFoundError:
            raise Camera_Exception
        except gst.AddError:
            raise Camera_Exception

    def init_pipeline(self):
        """Function pipeline constructs a pipeline containing a stream
        from the camera.
        """
        # Create pipeline:
        #                                   /-> screen_queue -> csp2 -> screen_sink
        #   img_src (camera) -> csp -> tee -|
        #                                   \-> image_queue -> image_sink
        #
        self.pipeline = gst.Pipeline("camera-pipeline")
        self.img_src = gst.element_factory_make("v4l2camsrc", "img_src")
        self.img_src.set_property('device', '/dev/video1')
        self.csp = gst.element_factory_make("ffmpegcolorspace", "csp")
        self.caps1 = gst.element_factory_make("capsfilter", "caps1")
        self.caps1.set_property('caps', gst.caps_from_string(
            "video/x-raw-rgb,width=%i,height=%i,bpp=24,depth=24"
            %(self.width, self.height)))
        self.csp2 = gst.element_factory_make("ffmpegcolorspace", "csp2")
        self.caps2 = gst.element_factory_make("capsfilter", "caps2")
        self.caps2.set_property('caps', gst.caps_from_string("video/x-raw-yuv"))
        self.tee = gst.element_factory_make('tee', 'tee')
        self.screen_queue = gst.element_factory_make('queue', 'screen_queue')
        self.image_queue = gst.element_factory_make('queue', 'image_queue')
        self.screen_sink = gst.element_factory_make("xvimagesink", "screen_sink")
        self.image_sink = gst.element_factory_make('fakesink', 'image_sink')
        self.pipeline.add(self.img_src, self.csp, self.caps1, self.csp2, self.caps2,
            self.tee, self.screen_queue, self.image_queue, self.screen_sink,
            self.image_sink)

        # Link the pipeline
        gst.element_link_many(self.img_src, self.csp, self.caps1, self.tee)
        if self.overlay:
            gst.element_link_many(self.tee, self.screen_queue, self.csp2,
            self.caps2, self.screen_sink)
        gst.element_link_many(self.tee, self.image_queue, self.image_sink)

        # Tell image_sink to emit handoff signals
        self.image_sink.set_property('signal-handoffs', True)

        self.pipeline.set_state(gst.STATE_PLAYING)

    def stop(self):
        self.pipeline.set_state(gst.STATE_NULL)

    def take_photo(self):
        """ This function tells the image_sink to handoff a picture buffer
            to save_buffer_cb.

            Parameters:
            cb: Callback function to be called after the photo is taken.
                Parameter will be a buffer with the image data.
        """
        debug("Taking photo!\n")
        # connect handoff signal to give the buffer to a function
        self.buffer_cb_id = self.image_sink.connect('handoff',
            self.save_buffer_cb)

    def save_buffer_cb(self, image_sink, buffer, pad):
        debug('camera: got buffer\n')
        self.buffer = buffer
        # disconnect signal so no more pictures will be taken
        image_sink.disconnect(self.buffer_cb_id)
        return True

    def expose_cb(self, widget, event):
        self.screen_sink.set_xwindow_id(widget.window.xid)
        return False

