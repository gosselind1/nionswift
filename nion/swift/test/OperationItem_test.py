# standard libraries
import contextlib
import copy
import functools
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import Cache
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Region
from nion.ui import Geometry
from nion.ui import Test


class TestProcessingClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        self.document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        self.document_controller = DocumentController.DocumentController(self.app.ui, self.document_model, workspace_id="library")
        self.display_panel = self.document_controller.selected_display_panel
        self.data_item = DataItem.DataItem(numpy.zeros((10, 10)))
        self.display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        self.document_model.append_data_item(self.data_item)
        self.display_panel.set_displayed_data_item(self.data_item)

    def tearDown(self):
        self.document_controller.close()

    # test processing against 1d data. doesn't test for correctness of the processing.
    def test_processing_1d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256), numpy.double))
        self.document_model.append_data_item(data_item_real)

        data_item_complex = DataItem.DataItem(numpy.zeros((256), numpy.complex128))
        self.document_model.append_data_item(data_item_complex)

        processing_list = []
        processing_list.append((data_item_real, self.document_model.get_fft_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item_real, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_real, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_real, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_real, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_real, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_real, self.document_model.get_convert_to_scalar_new, {}))
        processing_list.append((data_item_real, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            for name, value in params.items():
                data_item.maybe_data_source.computation._set_variable_value(name, value)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_2d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((8, 8), numpy.double))
        self.document_model.append_data_item(data_item_real)

        processing_list = []
        processing_list.append((data_item_real, self.document_model.get_fft_new, {}))
        processing_list.append((data_item_real, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_real, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_real, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_real, self.document_model.get_auto_correlate_new, {}))
        processing_list.append((data_item_real, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_real, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_real, self.document_model.get_crop_new, {}))
        processing_list.append((data_item_real, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        processing_list.append((data_item_real, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_real, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_real, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item_real, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_real, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            for name, value in params.items():
                data_item.maybe_data_source.computation._set_variable_value(name, value)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_3d(self):
        data_item_real = DataItem.DataItem(numpy.zeros((256,16,16), numpy.double))
        self.document_model.append_data_item(data_item_real)

        processing_list = []
        processing_list.append((data_item_real, self.document_model.get_slice_sum_new, {}))
        processing_list.append((data_item_real, self.document_model.get_pick_new, {}))
        processing_list.append((data_item_real, self.document_model.get_pick_region_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            for name, value in params.items():
                data_item.maybe_data_source.computation._set_variable_value(name, value)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_2d_rgb(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((8, 8, 3), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb)

        processing_list = []
        processing_list.append((data_item_rgb, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_crop_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        processing_list.append((data_item_rgb, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_rgb, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            for name, value in params.items():
                data_item.maybe_data_source.computation._set_variable_value(name, value)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_processing_2d_rgba(self):
        data_item_rgb = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb)

        processing_list = []
        processing_list.append((data_item_rgb, self.document_model.get_invert_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_crop_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        processing_list.append((data_item_rgb, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        processing_list.append((data_item_rgb, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_rgb, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            for name, value in params.items():
                data_item.maybe_data_source.computation._set_variable_value(name, value)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    def test_processing_2d_complex128(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((8, 8), numpy.complex128))
        self.document_model.append_data_item(data_item_complex)

        processing_list = []
        processing_list.append((data_item_complex, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            for name, value in params.items():
                data_item.maybe_data_source.computation._set_variable_value(name, value)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    def test_processing_2d_complex64(self):
        data_item_complex = DataItem.DataItem(numpy.zeros((8, 8), numpy.complex64))
        self.document_model.append_data_item(data_item_complex)

        processing_list = []
        processing_list.append((data_item_complex, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_projection_new, {}))
        processing_list.append((data_item_complex, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            for name, value in params.items():
                data_item.maybe_data_source.computation._set_variable_value(name, value)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.document_model.recompute_all()
            with display_specifier.buffered_data_source.data_ref() as data_ref:
                src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                self.assertEqual(src_data_item, source_data_item)
                self.assertIsNotNone(data_ref.data)
                self.assertIsNotNone(display_specifier.buffered_data_source.dimensional_calibrations)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[0], data_ref.data.shape)
                self.assertEqual(display_specifier.buffered_data_source.data_shape_and_dtype[1], data_ref.data.dtype)
                self.assertIsNotNone(display_specifier.buffered_data_source.data_shape_and_dtype[1].type)  # make sure we're returning a dtype
                self.assertEqual(len(display_specifier.buffered_data_source.dimensional_shape), len(display_specifier.buffered_data_source.dimensional_calibrations))

    # test processing against 2d data. doesn't test for correctness of the processing.
    def test_invalid_processings(self):

        data_item_none = DataItem.DataItem()
        self.document_model.append_data_item(data_item_none)

        data_item_real_0l = DataItem.DataItem(numpy.zeros((0), numpy.double))
        self.document_model.append_data_item(data_item_real_0l)
        data_item_real_0w = DataItem.DataItem(numpy.zeros((256,0), numpy.double))
        self.document_model.append_data_item(data_item_real_0w)
        data_item_real_0h = DataItem.DataItem(numpy.zeros((0,256), numpy.double))
        self.document_model.append_data_item(data_item_real_0h)
        data_item_real_0z = DataItem.DataItem(numpy.zeros((0, 8, 8), numpy.double))
        self.document_model.append_data_item(data_item_real_0z)
        data_item_real_0z0w = DataItem.DataItem(numpy.zeros((16,0,256), numpy.double))
        self.document_model.append_data_item(data_item_real_0z0w)
        data_item_real_0z0h = DataItem.DataItem(numpy.zeros((16,256,0), numpy.double))
        self.document_model.append_data_item(data_item_real_0z0h)

        data_item_complex_0l = DataItem.DataItem(numpy.zeros((0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0l)
        data_item_complex_0w = DataItem.DataItem(numpy.zeros((256,0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0w)
        data_item_complex_0h = DataItem.DataItem(numpy.zeros((0,256), numpy.double))
        self.document_model.append_data_item(data_item_complex_0h)
        data_item_complex_0z = DataItem.DataItem(numpy.zeros((0, 8, 8), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z)
        data_item_complex_0z0w = DataItem.DataItem(numpy.zeros((16,0,256), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z0w)
        data_item_complex_0z0h = DataItem.DataItem(numpy.zeros((16,256,0), numpy.double))
        self.document_model.append_data_item(data_item_complex_0z0h)

        data_item_rgb_0w = DataItem.DataItem(numpy.zeros((256,0, 3), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb_0w)
        data_item_rgb_0h = DataItem.DataItem(numpy.zeros((0,256, 3), numpy.uint8))
        self.document_model.append_data_item(data_item_rgb_0h)

        data_item_rgba_0w = DataItem.DataItem(numpy.zeros((256,0, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgba_0w)
        data_item_rgba_0h = DataItem.DataItem(numpy.zeros((0,256, 4), numpy.uint8))
        self.document_model.append_data_item(data_item_rgba_0h)

        data_list = (
            # data_item_none,
            data_item_real_0l, data_item_real_0w, data_item_real_0h, data_item_real_0z,
            data_item_real_0z0w, data_item_real_0z0h, data_item_complex_0l, data_item_complex_0w, data_item_complex_0h,
            data_item_complex_0z, data_item_complex_0z0w, data_item_complex_0z0h, data_item_rgb_0w, data_item_rgb_0h,
            data_item_rgba_0w, data_item_rgba_0h)

        processing_list = []
        for data_item in data_list:
            processing_list.append((data_item, self.document_model.get_fft_new, {}))
            processing_list.append((data_item, self.document_model.get_ifft_new, {}))
            processing_list.append((data_item, self.document_model.get_auto_correlate_new, {}))
            processing_list.append((data_item, functools.partial(self.document_model.get_cross_correlate_new, data_item), {}))
            processing_list.append((data_item, self.document_model.get_invert_new, {}))
            processing_list.append((data_item, self.document_model.get_sobel_new, {}))
            processing_list.append((data_item, self.document_model.get_laplace_new, {}))
            processing_list.append((data_item, self.document_model.get_gaussian_blur_new, {}))
            processing_list.append((data_item, self.document_model.get_median_filter_new, {}))
            processing_list.append((data_item, self.document_model.get_uniform_filter_new, {}))
            processing_list.append((data_item, self.document_model.get_crop_new, {}))
            processing_list.append((data_item, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
            processing_list.append((data_item, self.document_model.get_slice_sum_new, {}))
            processing_list.append((data_item, self.document_model.get_pick_new, {}))
            processing_list.append((data_item, self.document_model.get_pick_region_new, {}))
            processing_list.append((data_item, self.document_model.get_resample_new, {"width": 128, "height": 128}))
            processing_list.append((data_item, self.document_model.get_histogram_new, {}))
            processing_list.append((data_item, self.document_model.get_line_profile_new, {}))
            processing_list.append((data_item, self.document_model.get_projection_new, {}))
            processing_list.append((data_item, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            if data_item:
                for name, value in params.items():
                    data_item.maybe_data_source.computation._set_variable_value(name, value)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                self.document_model.recompute_all()
                with display_specifier.buffered_data_source.data_ref() as data_ref:
                    src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                    self.assertEqual(src_data_item, source_data_item)
                    self.assertIsNone(data_ref.data)
                    self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations, [])


    def test_processing_on_none(self):
        # TODO: this test makes less sense with computations; but leave it here until buffered_data_source and data_item merge.
        data_item = DataItem.DataItem()
        self.document_model.append_data_item(data_item)

        processing_list = []
        processing_list.append((data_item, self.document_model.get_fft_new, {}))
        processing_list.append((data_item, self.document_model.get_ifft_new, {}))
        processing_list.append((data_item, self.document_model.get_auto_correlate_new, {}))
        processing_list.append((data_item, functools.partial(self.document_model.get_cross_correlate_new, data_item), {}))
        processing_list.append((data_item, self.document_model.get_invert_new, {}))
        processing_list.append((data_item, self.document_model.get_sobel_new, {}))
        processing_list.append((data_item, self.document_model.get_laplace_new, {}))
        processing_list.append((data_item, self.document_model.get_gaussian_blur_new, {}))
        processing_list.append((data_item, self.document_model.get_median_filter_new, {}))
        processing_list.append((data_item, self.document_model.get_uniform_filter_new, {}))
        processing_list.append((data_item, self.document_model.get_crop_new, {}))
        processing_list.append((data_item, self.document_model.get_transpose_flip_new, {"do_transpose": True, "do_flip_v": True, "do_flip_h": True}))
        processing_list.append((data_item, self.document_model.get_slice_sum_new, {}))
        processing_list.append((data_item, self.document_model.get_pick_new, {}))
        processing_list.append((data_item, self.document_model.get_pick_region_new, {}))
        processing_list.append((data_item, self.document_model.get_resample_new, {"width": 128, "height": 128}))
        processing_list.append((data_item, self.document_model.get_histogram_new, {}))
        processing_list.append((data_item, self.document_model.get_line_profile_new, {}))
        processing_list.append((data_item, self.document_model.get_projection_new, {}))
        processing_list.append((data_item, self.document_model.get_convert_to_scalar_new, {}))

        for source_data_item, fn, params in processing_list:
            data_item = fn(source_data_item)
            if data_item:
                for name, value in params.items():
                    data_item.maybe_data_source.computation._set_variable_value(name, value)
                display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                self.document_model.recompute_all()
                with display_specifier.buffered_data_source.data_ref() as data_ref:
                    src_data_item = self.document_model.resolve_object_specifier(data_item.maybe_data_source.computation.variables[0].variable_specifier).data_item
                    self.assertEqual(src_data_item, source_data_item)
                    self.assertIsNone(data_ref.data)
                    self.assertEqual(display_specifier.buffered_data_source.dimensional_calibrations, [])

    def test_crop_2d_processing_returns_correct_dimensional_shape_and_data_shape(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((20,10), numpy.double))
            crop_region = Region.RectRegion()
            crop_region.bounds = (0.2, 0.3), (0.5, 0.5)
            data_item.maybe_data_source.add_region(crop_region)
            document_model.append_data_item(data_item)
            real_data_item = document_model.get_crop_new(data_item, crop_region)
            real_display_specifier = DataItem.DisplaySpecifier.from_data_item(real_data_item)
            document_model.recompute_all()
            # make sure we get the right shape
            self.assertEqual(real_display_specifier.buffered_data_source.dimensional_shape, (10, 5))
            with real_display_specifier.buffered_data_source.data_ref() as data_real_accessor:
                self.assertEqual(data_real_accessor.data.shape, (10, 5))

    def test_fft_2d_dtype(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.float64))
            document_model.append_data_item(data_item)
            fft_data_item = document_model.get_fft_new(data_item)
            fft_display_specifier = DataItem.DisplaySpecifier.from_data_item(fft_data_item)
            document_model.recompute_all()
            with fft_display_specifier.buffered_data_source.data_ref() as fft_data_ref:
                self.assertEqual(fft_data_ref.data.shape, (16, 16))
                self.assertEqual(fft_data_ref.data.dtype, numpy.dtype(numpy.complex128))

    def test_convert_complex128_to_scalar_results_in_float64(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((16, 16), numpy.complex128))
            document_model.append_data_item(data_item)
            scalar_data_item = document_model.get_convert_to_scalar_new(data_item)
            scalar_display_specifier = DataItem.DisplaySpecifier.from_data_item(scalar_data_item)
            document_model.recompute_all()
            with scalar_display_specifier.buffered_data_source.data_ref() as scalar_data_ref:
                self.assertEqual(scalar_data_ref.data.dtype, numpy.dtype(numpy.float64))

    def test_rgba_invert_processing_should_retain_alpha(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            rgba_data_item = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
            document_model.append_data_item(rgba_data_item)
            rgba_display_specifier = DataItem.DisplaySpecifier.from_data_item(rgba_data_item)
            with rgba_display_specifier.buffered_data_source.data_ref() as data_ref:
                data_ref.master_data[:] = (20,40,60,100)
                data_ref.master_data_updated()
            rgba2_data_item = document_model.get_invert_new(rgba_data_item)
            rgba2_display_specifier = DataItem.DisplaySpecifier.from_data_item(rgba2_data_item)
            document_model.recompute_all()
            with rgba2_display_specifier.buffered_data_source.data_ref() as data_ref:
                pixel = data_ref.data[0,0,...]
                self.assertEqual(pixel[0], 255 - 20)
                self.assertEqual(pixel[1], 255 - 40)
                self.assertEqual(pixel[2], 255 - 60)
                self.assertEqual(pixel[3], 100)

    def test_deepcopy_of_crop_processing_should_copy_roi(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_rgba = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
            crop_region = Region.RectRegion()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item_rgba.maybe_data_source.add_region(crop_region)
            self.document_model.append_data_item(data_item_rgba)
            data_item_rgba2 = document_model.get_crop_new(data_item_rgba, crop_region)
            data_item_rgba2_copy = copy.deepcopy(data_item_rgba2)
            # make sure the computation was not copied
            self.assertNotEqual(data_item_rgba2.maybe_data_source.computation, data_item_rgba2_copy.maybe_data_source.computation)

    def test_snapshot_of_processing_should_copy_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item_rgba = DataItem.DataItem(numpy.zeros((8, 8, 4), numpy.uint8))
            document_model.append_data_item(data_item_rgba)
            data_item_rgba2 = document_model.get_invert_new(data_item_rgba)
            document_model.recompute_all()
            data_item_rgba2_ss = document_model.get_snapshot_new(data_item_rgba2)
            self.assertTrue(data_item_rgba2_ss.maybe_data_source.has_data)

    def test_snapshot_empty_data_item_should_produce_empty_data_item(self):
        data_item = DataItem.DataItem()
        data_item.append_data_source(DataItem.BufferedDataSource())
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.assertIsNone(display_specifier.buffered_data_source.data)
        self.assertIsNone(display_specifier.buffered_data_source.data_dtype)
        self.assertIsNone(display_specifier.buffered_data_source.data_shape)
        snapshot_data_item = data_item.snapshot()
        snapshot_display_specifier = DataItem.DisplaySpecifier.from_data_item(snapshot_data_item)
        self.assertIsNone(snapshot_display_specifier.buffered_data_source.data)
        self.assertIsNone(snapshot_display_specifier.buffered_data_source.data_dtype)
        self.assertIsNone(snapshot_display_specifier.buffered_data_source.data_shape)

    def test_snapshot_of_processing_should_copy_calibrations_not_dimensional_calibrations(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            # setup
            display_specifier.buffered_data_source.set_dimensional_calibration(0, Calibration.Calibration(5.0, 2.0, u"nm"))
            display_specifier.buffered_data_source.set_dimensional_calibration(1, Calibration.Calibration(5.0, 2.0, u"nm"))
            display_specifier.buffered_data_source.set_intensity_calibration(Calibration.Calibration(7.5, 2.5, u"ll"))
            data_item2 = document_model.get_invert_new(data_item)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item2)
            document_model.recompute_all()
            # make sure our assumptions are correct
            self.assertEqual(len(display_specifier.buffered_data_source.dimensional_calibrations), 2)
            self.assertEqual(len(display_specifier2.buffered_data_source.dimensional_calibrations), 2)
            # take snapshot
            snapshot_data_item = document_model.get_snapshot_new(data_item2)
            buffered_data_source = snapshot_data_item.maybe_data_source
            # check calibrations
            self.assertEqual(len(buffered_data_source.dimensional_calibrations), 2)
            self.assertEqual(buffered_data_source.dimensional_calibrations[0].scale, 2.0)
            self.assertEqual(buffered_data_source.dimensional_calibrations[0].offset, 5.0)
            self.assertEqual(buffered_data_source.dimensional_calibrations[0].units, u"nm")
            self.assertEqual(buffered_data_source.dimensional_calibrations[1].scale, 2.0)
            self.assertEqual(buffered_data_source.dimensional_calibrations[1].offset, 5.0)
            self.assertEqual(buffered_data_source.dimensional_calibrations[1].units, u"nm")
            self.assertEqual(buffered_data_source.intensity_calibration.scale, 2.5)
            self.assertEqual(buffered_data_source.intensity_calibration.offset, 7.5)
            self.assertEqual(buffered_data_source.intensity_calibration.units, u"ll")

    def test_crop_2d_processing_on_calibrated_data_results_in_calibration_with_correct_offset(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((20, 10), numpy.double))
            crop_region = Region.RectRegion()
            crop_region.bounds = (0.2, 0.3), (0.5, 0.5)
            data_item.maybe_data_source.add_region(crop_region)
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            spatial_calibration_0 = display_specifier.buffered_data_source.dimensional_calibrations[0]
            spatial_calibration_0.offset = 20.0
            spatial_calibration_0.scale = 5.0
            spatial_calibration_0.units = "dogs"
            spatial_calibration_1 = display_specifier.buffered_data_source.dimensional_calibrations[1]
            spatial_calibration_1.offset = 55.0
            spatial_calibration_1.scale = 5.5
            spatial_calibration_1.units = "cats"
            display_specifier.buffered_data_source.set_dimensional_calibration(0, spatial_calibration_0)
            display_specifier.buffered_data_source.set_dimensional_calibration(1, spatial_calibration_1)
            data_item2 = document_model.get_crop_new(data_item, crop_region)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item2)
            document_model.recompute_all()
            # make sure the calibrations are correct
            self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].offset, 20.0 + 20 * 0.2 * 5.0)
            self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[1].offset, 55.0 + 10 * 0.3 * 5.5)
            self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].scale, 5.0)
            self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[1].scale, 5.5)
            self.assertEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].units, "dogs")
            self.assertEqual(display_specifier2.buffered_data_source.dimensional_calibrations[1].units, "cats")

    def test_projection_2d_processing_on_calibrated_data_results_in_calibration_with_correct_offset(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((20, 10), numpy.double))
            document_model.append_data_item(data_item)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            spatial_calibration_0 = display_specifier.buffered_data_source.dimensional_calibrations[0]
            spatial_calibration_0.offset = 20.0
            spatial_calibration_0.scale = 5.0
            spatial_calibration_0.units = "dogs"
            spatial_calibration_1 = display_specifier.buffered_data_source.dimensional_calibrations[1]
            spatial_calibration_1.offset = 55.0
            spatial_calibration_1.scale = 5.5
            spatial_calibration_1.units = "cats"
            display_specifier.buffered_data_source.set_dimensional_calibration(0, spatial_calibration_0)
            display_specifier.buffered_data_source.set_dimensional_calibration(1, spatial_calibration_1)
            data_item2 = document_model.get_projection_new(data_item)
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(data_item2)
            document_model.recompute_all()
            # make sure the calibrations are correct
            self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].offset, 55.0)
            self.assertAlmostEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].scale, 5.5)
            self.assertEqual(display_specifier2.buffered_data_source.dimensional_calibrations[0].units, "cats")

    def disabled_test_removing_computation_with_multiple_associated_regions_removes_all_regions(self):
        self.assertFalse(True)

    def test_crop_works_on_selected_region_without_exception(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        crop_region = Region.RectRegion()
        crop_region.center = (0.5, 0.5)
        crop_region.size = (0.5, 1.0)
        data_item.maybe_data_source.add_region(crop_region)
        display_specifier.display.graphic_selection.set(0)
        document_controller.processing_crop().data_item
        document_controller.close()

    def test_remove_graphic_for_crop_removes_processed_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        crop_region = Region.RectRegion()
        crop_region.center = (0.5, 0.5)
        crop_region.size = (0.5, 1.0)
        data_item.maybe_data_source.add_region(crop_region)
        display_specifier.display.graphic_selection.set(0)
        cropped_data_item = document_controller.processing_crop().data_item
        document_controller.periodic()  # TODO: remove need to let the inspector catch up
        self.assertEqual(len(display_specifier.display.drawn_graphics), 1)
        self.assertTrue(cropped_data_item in document_model.data_items)
        display_specifier.display.graphic_selection.clear()
        display_specifier.display.graphic_selection.add(0)
        # make sure assumptions are correct
        self.assertEqual(document_model.get_source_data_items(cropped_data_item)[0], data_item)
        self.assertTrue(cropped_data_item in document_model.data_items)
        # remove the graphic and make sure things are as expected
        document_controller.remove_graphic()
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        self.assertEqual(len(display_specifier.display.graphic_selection.indexes), 0)  # disabled until test_remove_line_profile_updates_graphic_selection
        self.assertFalse(cropped_data_item in document_model.data_items)
        # clean up
        document_controller.close()

    def test_remove_graphic_for_crop_combined_with_another_processing_removes_processed_data_item(self):
        document_model = DocumentModel.DocumentModel()
        data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
        document_model.append_data_item(data_item)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        display_panel.set_displayed_data_item(data_item)
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        crop_region = Region.RectRegion()
        crop_region.center = (0.5, 0.5)
        crop_region.size = (0.5, 1.0)
        data_item.maybe_data_source.add_region(crop_region)
        display_specifier.display.graphic_selection.set(0)
        projection_data_item = document_controller.processing_projection().data_item
        document_controller.periodic()  # TODO: remove need to let the inspector catch up
        self.assertTrue(projection_data_item in document_model.data_items)
        display_specifier.display.graphic_selection.clear()
        display_specifier.display.graphic_selection.add(0)
        # make sure assumptions are correct
        self.assertEqual(document_model.get_source_data_items(projection_data_item)[0], data_item)
        self.assertTrue(projection_data_item in document_model.data_items)
        # remove the graphic and make sure things are as expected
        document_controller.remove_graphic()
        self.assertEqual(len(display_specifier.display.drawn_graphics), 0)
        self.assertEqual(len(display_specifier.display.graphic_selection.indexes), 0)  # disabled until test_remove_line_profile_updates_graphic_selection
        self.assertFalse(projection_data_item in document_model.data_items)
        # clean up
        document_controller.close()

    def test_modifying_processing_results_in_data_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # set up the data items
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item)
            blurred_data_item = document_model.get_gaussian_blur_new(data_item)
            blurred_display_specifier = DataItem.DisplaySpecifier.from_data_item(blurred_data_item)
            # establish listeners
            data_changed_ref = [False]
            display_changed_ref = [False]
            def data_item_content_changed(changes):
                data_changed_ref[0] = data_changed_ref[0] or DataItem.DATA in changes
            with contextlib.closing(blurred_data_item.data_item_content_changed_event.listen(data_item_content_changed)):
                def display_changed():
                    display_changed_ref[0] = True
                with contextlib.closing(blurred_display_specifier.display.display_changed_event.listen(display_changed)):
                    # modify processing. make sure data and dependent data gets updated.
                    data_changed_ref[0] = False
                    display_changed_ref[0] = False
                    blurred_data_item.maybe_data_source.computation._set_variable_value("sigma", 0.1)
                    document_model.recompute_all()
                    self.assertTrue(data_changed_ref[0])
                    self.assertTrue(display_changed_ref[0])

    def test_modifying_processing_region_results_in_data_computation(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            # set up the data items
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Region.RectRegion()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.maybe_data_source.add_region(crop_region)
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            document_model.append_data_item(data_item)
            cropped_data_item = document_model.get_crop_new(data_item, crop_region)
            cropped_display_specifier = DataItem.DisplaySpecifier.from_data_item(cropped_data_item)
            # establish listeners
            data_changed_ref = [False]
            display_changed_ref = [False]
            def data_item_content_changed(changes):
                data_changed_ref[0] = data_changed_ref[0] or DataItem.DATA in changes
            with contextlib.closing(cropped_data_item.data_item_content_changed_event.listen(data_item_content_changed)):
                def display_changed():
                    display_changed_ref[0] = True
                with contextlib.closing(cropped_display_specifier.display.display_changed_event.listen(display_changed)):
                    # modify processing. make sure data and dependent data gets updated.
                    data_changed_ref[0] = False
                    display_changed_ref[0] = False
                    crop_region.center = (0.51, 0.51)
                    document_model.recompute_all()
                    self.assertTrue(data_changed_ref[0])
                    self.assertTrue(display_changed_ref[0])

    def test_changing_region_does_not_trigger_fft_recompute(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            crop_region = Region.RectRegion()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            data_item.maybe_data_source.add_region(crop_region)
            document_model.append_data_item(data_item)
            fft_data_item = document_model.get_fft_new(data_item)
            fft_display_specifier = DataItem.DisplaySpecifier.from_data_item(fft_data_item)
            crop_data_item = document_model.get_crop_new(data_item, crop_region)
            crop_display_specifier = DataItem.DisplaySpecifier.from_data_item(crop_data_item)
            document_model.recompute_all()
            self.assertFalse(fft_display_specifier.buffered_data_source.computation.needs_update)
            self.assertFalse(crop_display_specifier.buffered_data_source.computation.needs_update)
            crop_region.bounds = Geometry.FloatRect(crop_region.bounds[0], Geometry.FloatPoint(0.1, 0.1))
            self.assertTrue(crop_display_specifier.buffered_data_source.computation.needs_update)
            self.assertFalse(fft_display_specifier.buffered_data_source.computation.needs_update)

    def test_removing_source_of_cross_correlation_does_not_throw_exception(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8), numpy.uint32))
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            document_model.get_cross_correlate_new(data_item1, data_item2)
            document_model.recompute_all()
            document_model.remove_data_item(data_item1)
            document_model.recompute_all()

    def test_crop_of_slice_of_3d_handles_dimensions(self):
        # the bug was that slice processing returned the wrong number of dimensions
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.zeros((16, 32, 32), numpy.float))
            document_model.append_data_item(data_item)
            slice_data_item = document_model.get_slice_sum_new(data_item)
            document_model.recompute_all()
            crop_region = Region.RectRegion()
            crop_region.bounds = (0.25, 0.25), (0.5, 0.5)
            slice_data_item.maybe_data_source.add_region(crop_region)
            crop_data_item = document_model.get_crop_new(slice_data_item, crop_region)
            document_model.recompute_all()


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
