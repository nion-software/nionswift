import collections
import copy
import datetime
import gettext
import logging
import typing
import uuid

from nion.swift.model import Utility

_ = gettext.gettext



def migrate_to_latest(reader_info_list, library_updates) -> None:
    migrate_to_v2(reader_info_list)
    migrate_to_v3(reader_info_list)
    migrate_to_v4(reader_info_list)
    migrate_to_v5(reader_info_list)
    migrate_to_v6(reader_info_list)
    migrate_to_v7(reader_info_list)
    migrate_to_v8(reader_info_list)
    migrate_to_v9(reader_info_list)
    migrate_to_v10(reader_info_list)
    migrate_to_v11(reader_info_list)
    migrate_to_v12(reader_info_list, library_updates)
    migrate_to_v13(reader_info_list, library_updates)

    # TODO: file format. Rename workspaces to workspace_layouts.
    # TODO: store session metadata as regular metadata
    # TODO: consolidate specifier fields in computation variable into a single dict (specifier, secondary_specifier, property_name)


def migrate_library_to_latest(library_properties: typing.Dict) -> None:
    migrate_library_to_v2(library_properties)
    migrate_library_to_v3(library_properties)


def transform_to_latest(properties):
    return properties


def transform_from_latest(properties):
    return properties


def migrate_to_v13(reader_info_list, library_updates):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 12:
                reader_info.changed_ref[0] = True
                # import pprint; pprint.pprint(properties)
                # version 12 -> 13 moves non-display related data into data source and moves data item into library storage.

                data_source_properties = properties.pop("data_source", None)

                data_item_uuid_str = properties["uuid"]
                data_item_uuid = uuid.UUID(data_item_uuid_str)

                # move the properties that were in description to data source if it exists

                title = properties.get("description", dict()).get("title")
                caption = properties.get("description", dict()).get("caption")

                if data_source_properties is not None:
                    if title is not None:
                        data_source_properties["title"] = title
                    if caption is not None:
                        data_source_properties["caption"] = caption
                else:
                    if title is not None:
                        properties["title"] = title
                    if caption is not None:
                        properties["caption"] = caption

                properties.pop("description", None)

                # move the timezone properties to data source

                timezone = properties.pop("timezone", None)
                timezone_offset = properties.pop("timezone_offset", None)

                if data_source_properties is not None:
                    if timezone is not None:
                        data_source_properties["timezone"] = timezone
                    if timezone_offset is not None:
                        data_source_properties["timezone_offset"] = timezone_offset
                    data_source_properties.get("metadata", dict()).pop("description", None)

                # copy session id, category to data source; move session data

                session_id = properties.get("session_id", None)
                category = properties.get("category", None)
                session_data = properties.pop("session_metadata", None)

                if data_source_properties is not None:
                    if session_id is not None:
                        data_source_properties["session_id"] = session_id
                    if category is not None:
                        data_source_properties["category"] = category
                    if session_data is not None:
                        data_source_properties["session"] = session_data

                    data_source_properties.pop("uuid", None)

                    properties.update(data_source_properties)

                properties.pop("connections", None)
                properties.pop("data_item_uuids", None)

                properties["type"] = "data-item"

                # move the display properties into a display item

                display_items = list()

                display_properties_list = properties.pop("displays", list())

                if len(display_properties_list) > 0:
                    display_properties = display_properties_list[0]
                    display_item_properties = dict()
                    display_item_properties["type"] = "display_item"
                    display_item_properties["uuid"] = str(uuid.uuid4())
                    if "created" in properties:
                        display_item_properties["created"] = properties.get("created")
                    if "modified" in properties:
                        display_item_properties["modified"] = properties.get("modified")
                    # display_calibrated_values is superseded by calibration_style_id
                    if "dimensional_calibration_style" in display_properties:
                        display_item_properties["calibration_style_id"] = display_properties["dimensional_calibration_style"]
                    else:
                        display_item_properties["calibration_style_id"] = "calibrated" if display_properties.get("display_calibrated_values", True) else "pixels-center"
                    display_properties.pop("dimensional_calibration_style", None)
                    display_properties.pop("display_calibrated_values", None)
                    display_item_properties["display"] = display_properties
                    display_item_properties["display_type"] = display_properties.pop("display_type", None)
                    display_item_properties["graphics"] = display_properties.pop("graphics", list())
                    display_data_properties = dict()
                    new_display_properties = dict()
                    if "complex_data_type" in display_properties:
                        display_data_properties["complex_data_type"] = display_properties.pop("complex_data_type")
                    if "display_limits" in display_properties:
                        display_data_properties["display_limits"] = display_properties.pop("display_limits")
                    if "color_map_id" in display_properties:
                        display_data_properties["color_map_id"] = display_properties.pop("color_map_id")
                    if "sequence_index" in display_properties:
                        display_data_properties["sequence_index"] = display_properties.pop("sequence_index")
                    if "collection_index" in display_properties:
                        display_data_properties["collection_index"] = display_properties.pop("collection_index")
                    if "slice_center" in display_properties:
                        display_data_properties["slice_center"] = display_properties.pop("slice_center")
                    if "slice_width" in display_properties:
                        display_data_properties["slice_width"] = display_properties.pop("slice_width")
                    if "y_min" in display_properties:
                        new_display_properties["y_min"] = display_properties.pop("y_min")
                    if "y_max" in display_properties:
                        new_display_properties["y_max"] = display_properties.pop("y_max")
                    if "y_style" in display_properties:
                        new_display_properties["y_style"] = display_properties.pop("y_style")
                    if "image_zoom" in display_properties:
                        new_display_properties["image_zoom"] = display_properties.pop("image_zoom")
                    if "image_position" in display_properties:
                        new_display_properties["image_position"] = display_properties.pop("image_position")
                    if "image_canvas_mode" in display_properties:
                        new_display_properties["image_canvas_mode"] = display_properties.pop("image_canvas_mode")
                    if "left_channel" in display_properties:
                        new_display_properties["left_channel"] = display_properties.pop("left_channel")
                    if "right_channel" in display_properties:
                        new_display_properties["right_channel"] = display_properties.pop("right_channel")
                    if "legend_labels" in display_properties:
                        new_display_properties["legend_labels"] = display_properties.pop("legend_labels")
                    if "display_script" in display_properties:
                        new_display_properties["display_script"] = display_properties.pop("display_script")
                    if new_display_properties:
                        display_item_properties["display_properties"] = new_display_properties
                    display_data_properties["data_item_reference"] = data_item_uuid_str
                    display_data_properties["type"] = "display_data_channel"
                    display_data_properties["uuid"] = str(uuid.uuid4())
                    display_items.append(display_item_properties)
                    display_item_properties["display_data_channels"] = [display_data_properties]
                    display_item_properties["session_id"] = session_id

                library_updates.setdefault(data_item_uuid, dict()).setdefault("display_items", list()).extend(display_items)

                properties["version"] = 13

                logging.getLogger("migration").debug("Updated {} to {} (separate data item/move display to lirbary)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v12(reader_info_list, library_updates):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 11:
                reader_info.changed_ref[0] = True
                # import pprint; pprint.pprint(properties)
                # version 11 -> 12 moves connections and computations out of data item and into library.

                data_item_uuid_str = properties["uuid"]
                data_item_uuid = uuid.UUID(data_item_uuid_str)

                computation_dict = properties.get("computation", dict())
                if computation_dict:
                    data_item_specifier = {"type": "data_item_object", "uuid": data_item_uuid_str, "version": 1}
                    computation_dict["results"] = [{"name": "target", "label": "Target", "specifier": data_item_specifier, "type": "output", "uuid": str(uuid.uuid4())}]
                    computation_dict["source_uuid"] = data_item_uuid_str
                    library_updates.setdefault(data_item_uuid, dict()).setdefault("computations", list()).append(computation_dict)
                    properties.pop("computation", None)

                for connection_dict in properties.get("connections", list()):
                    connection_dict["parent_uuid"] = data_item_uuid_str
                    library_updates.setdefault(data_item_uuid, dict()).setdefault("connections", list()).append(connection_dict)
                    properties.pop("connections", None)

                properties["version"] = 12

                logging.getLogger("migration").debug("Updated {} to {} (move connections/computations to library)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v11(reader_info_list):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 10:
                reader_info.changed_ref[0] = True
                # pprint.pprint(properties)
                # version 10 -> 11 changes computed data items to combined crop, merges data source into data item.
                data_source_dicts = properties.get("data_sources", list())
                if len(data_source_dicts) > 0:
                    data_source_dict = data_source_dicts[0]

                    # update computation content
                    variables_dict = data_source_dict.get("computation", dict()).get("variables")
                    processing_id = data_source_dict.get("computation", dict()).get("processing_id")
                    if variables_dict and processing_id:
                        # import pprint
                        # print(pprint.pformat(variables_dict))
                        variable_lookup = dict()
                        for variable_dict in variables_dict:
                            variable_lookup[variable_dict['name']] = variable_dict
                        if "src" in variable_lookup and "crop_region" in variable_lookup:
                            variable_lookup["src"]["secondary_specifier"] = copy.deepcopy(variable_lookup["crop_region"]["specifier"])
                            variables_dict.remove(variable_lookup["crop_region"])
                        if "src1" in variable_lookup and "crop_region0" in variable_lookup:
                            variable_lookup["src1"]["secondary_specifier"] = copy.deepcopy(variable_lookup["crop_region0"]["specifier"])
                            variables_dict.remove(variable_lookup["crop_region0"])
                        if "src2" in variable_lookup and "crop_region1" in variable_lookup:
                            variable_lookup["src2"]["secondary_specifier"] = copy.deepcopy(variable_lookup["crop_region1"]["specifier"])
                            variables_dict.remove(variable_lookup["crop_region1"])
                        # print(pprint.pformat(variables_dict))
                        # print("-----------------------")

                    # update computation location
                    computation = data_source_dict.get("computation")
                    if computation:
                        properties["computation"] = computation
                    data_source_dict.pop("computation", None)

                    # update displays location
                    displays = data_source_dict.get("displays")
                    if displays and len(displays) > 0:
                        properties["displays"] = displays[0:1]
                    data_source_dict.pop("displays", None)

                    # update data_source location
                    properties["data_source"] = data_source_dict

                # get rid of data_sources
                properties.pop("data_sources", None)

                # change metadata to description
                properties["description"] = properties.pop("metadata", dict()).get("description", dict())

                properties["version"] = 11

                logging.getLogger("migration").debug("Updated {} to {} (computed data items combined crop, data source merge)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v10(reader_info_list):
    translate_region_type = {"point-region": "point-graphic", "line-region": "line-profile-graphic", "rectangle-region": "rect-graphic", "ellipse-region": "ellipse-graphic",
        "interval-region": "interval-graphic"}
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 9:
                reader_info.changed_ref[0] = True
                # import pprint
                # pprint.pprint(properties)
                for data_source in properties.get("data_sources", list()):
                    displays = data_source.get("displays", list())
                    if len(displays) > 0:
                        display = displays[0]
                        for region in data_source.get("regions", list()):
                            graphic = dict()
                            graphic["type"] = translate_region_type[region["type"]]
                            graphic["uuid"] = region["uuid"]
                            region_id = region.get("region_id")
                            if region_id is not None:
                                graphic["graphic_id"] = region_id
                            label = region.get("label")
                            if label is not None:
                                graphic["label"] = label
                            is_position_locked = region.get("is_position_locked")
                            if is_position_locked is not None:
                                graphic["is_position_locked"] = is_position_locked
                            is_shape_locked = region.get("is_shape_locked")
                            if is_shape_locked is not None:
                                graphic["is_shape_locked"] = is_shape_locked
                            is_bounds_constrained = region.get("is_bounds_constrained")
                            if is_bounds_constrained is not None:
                                graphic["is_bounds_constrained"] = is_bounds_constrained
                            center = region.get("center")
                            size = region.get("size")
                            if center is not None and size is not None:
                                graphic["bounds"] = (center[0] - size[0] * 0.5, center[1] - size[1] * 0.5), (size[0], size[1])
                            start = region.get("start")
                            if start is not None:
                                graphic["start"] = start
                            end = region.get("end")
                            if end is not None:
                                graphic["end"] = end
                            width = region.get("width")
                            if width is not None:
                                graphic["width"] = width
                            position = region.get("position")
                            if position is not None:
                                graphic["position"] = position
                            interval = region.get("interval")
                            if interval is not None:
                                graphic["interval"] = interval
                            display.setdefault("graphics", list()).append(graphic)
                    data_source.pop("regions", None)
                for connection in properties.get("connections", list()):
                    if connection.get("type") == "interval-list-connection":
                        connection["source_uuid"] = properties["data_sources"][0]["displays"][0]["uuid"]
                # pprint.pprint(properties)
                # version 9 -> 10 merges regions into graphics.
                properties["version"] = 10
                logging.getLogger("migration").debug("Updated {} to {} (regions merged into graphics)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v9(reader_info_list):
    data_source_uuid_to_data_item_uuid = dict()
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            data_source_dicts = properties.get("data_sources", list())
            for data_source_dict in data_source_dicts:
                data_source_uuid_to_data_item_uuid[data_source_dict["uuid"]] = properties["uuid"]
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 8:
                reader_info.changed_ref[0] = True
                # version 8 -> 9 changes operations to computations
                data_source_dicts = properties.get("data_sources", list())
                for data_source_dict in data_source_dicts:
                    metadata = data_source_dict.get("metadata", dict())
                    hardware_source_dict = metadata.get("hardware_source", dict())
                    high_tension_v = hardware_source_dict.get("extra_high_tension")
                    # hardware_source_dict.pop("extra_high_tension", None)
                    if high_tension_v:
                        autostem_dict = hardware_source_dict.setdefault("autostem", dict())
                        autostem_dict["high_tension_v"] = high_tension_v
                data_source_dicts = properties.get("data_sources", list())
                ExpressionInfo = collections.namedtuple("ExpressionInfo", ["label", "expression", "processing_id", "src_labels", "src_names", "variables", "use_display_data"])
                info = dict()
                info["fft-operation"] = ExpressionInfo(_("FFT"), "xd.fft({src})", "fft", [_("Source")], ["src"], list(), True)
                info["inverse-fft-operation"] = ExpressionInfo(_("Inverse FFT"), "xd.ifft({src})", "inverse-fft", [_("Source")], ["src"], list(), False)
                info["auto-correlate-operation"] = ExpressionInfo(_("Auto Correlate"), "xd.autocorrelate({src})", "auto-correlate", [_("Source")], ["src"], list(), True)
                info["cross-correlate-operation"] = ExpressionInfo(_("Cross Correlate"), "xd.crosscorrelate({src1}, {src2})", "cross-correlate", [_("Source1"), _("Source2")], ["src1", "src2"], list(), True)
                info["invert-operation"] = ExpressionInfo(_("Invert"), "xd.invert({src})", "invert", [_("Source")], ["src"], list(), True)
                info["sobel-operation"] = ExpressionInfo(_("Sobel"), "xd.sobel({src})", "sobel", [_("Source")], ["src"], list(), True)
                info["laplace-operation"] = ExpressionInfo(_("Laplace"), "xd.laplace({src})", "laplace", [_("Source")], ["src"], list(), True)
                sigma_var = {'control_type': 'slider', 'label': _('Sigma'), 'name': 'sigma', 'type': 'variable', 'value': 3.0, 'value_default': 3.0, 'value_max': 100.0, 'value_min': 0.0, 'value_type': 'real'}
                info["gaussian-blur-operation"] = ExpressionInfo(_("Gaussian Blur"), "xd.gaussian_blur({src}, sigma)", "gaussian-blur", [_("Source")], ["src"], [sigma_var], True)
                filter_size_var = {'label': _("Size"), 'op_name': 'size', 'name': 'filter_size', 'type': 'variable', 'value': 3, 'value_default': 3, 'value_max': 100, 'value_min': 1, 'value_type': 'integral'}
                info["median-filter-operation"] = ExpressionInfo(_("Median Filter"), "xd.median_filter({src}, filter_size)", "median-filter", [_("Source")], ["src"], [filter_size_var], True)
                info["uniform-filter-operation"] = ExpressionInfo(_("Uniform Filter"), "xd.uniform_filter({src}, filter_size)", "uniform-filter", [_("Source")], ["src"], [filter_size_var], True)
                do_transpose_var = {'label': _("Tranpose"), 'op_name': 'transpose', 'name': 'do_transpose', 'type': 'variable', 'value': False, 'value_default': False, 'value_type': 'boolean'}
                do_flip_v_var = {'label': _("Flip Vertical"), 'op_name': 'flip_horizontal', 'name': 'do_flip_v', 'type': 'variable', 'value': False, 'value_default': False, 'value_type': 'boolean'}
                do_flip_h_var = {'label': _("Flip Horizontal"), 'op_name': 'flip_vertical', 'name': 'do_flip_h', 'type': 'variable', 'value': False, 'value_default': False, 'value_type': 'boolean'}
                info["transpose-flip-operation"] = ExpressionInfo(_("Transpose/Flip"), "xd.transpose_flip({src}, do_transpose, do_flip_v, do_flip_h)", "transpose-flip", [_("Source")], ["src"], [do_transpose_var, do_flip_v_var, do_flip_h_var], True)
                info["crop-operation"] = ExpressionInfo(_("Crop"), "{src}", "crop", [_("Source")], ["src"], list(), False)
                center_var = {'label': _("Center"), 'op_name': 'slice_center', 'name': 'center', 'type': 'variable', 'value': 0, 'value_default': 0, 'value_min': 0, 'value_type': 'integral'}
                width_var = {'label': _("Width"), 'op_name': 'slice_width', 'name': 'width', 'type': 'variable', 'value': 1, 'value_default': 1, 'value_min': 1, 'value_type': 'integral'}
                info["slice-operation"] = ExpressionInfo(_("Slice"), "xd.slice_sum({src}, center, width)", "slice", [_("Source")], ["src"], [center_var, width_var], False)
                pt_var = {'label': _("Pick Point"), 'name': 'pick_region', 'type': 'variable', 'value_type': 'point'}
                info["pick-operation"] = ExpressionInfo(_("Pick"), "xd.pick({src}, pick_region.position)", "pick-point", [_("Source")], ["src"], [pt_var], False)
                info["projection-operation"] = ExpressionInfo(_("Sum"), "xd.sum({src}, src.xdata.datum_dimension_indexes[0])", "sum", [_("Source")], ["src"], list(), False)
                width_var = {'label': _("Width"), 'name': 'width', 'type': 'variable', 'value': 256, 'value_default': 256, 'value_min': 1, 'value_type': 'integral'}
                height_var = {'label': _("Height"), 'name': 'height', 'type': 'variable', 'value': 256, 'value_default': 256, 'value_min': 1, 'value_type': 'integral'}
                info["resample-operation"] = ExpressionInfo(_("Reshape"), "xd.resample_image({src}, (height, width))", "resample", [_("Source")], ["src"], [width_var, height_var], True)
                bins_var = {'label': _("Bins"), 'name': 'bins', 'type': 'variable', 'value': 256, 'value_default': 256, 'value_min': 2, 'value_type': 'integral'}
                info["histogram-operation"] = ExpressionInfo(_("Histogram"), "xd.histogram({src}, bins)", "histogram", [_("Source")], ["src"], [bins_var], True)
                line_var = {'label': _("Line Profile"), 'name': 'line_region', 'type': 'variable', 'value_type': 'line'}
                info["line-profile-operation"] = ExpressionInfo(_("Line Profile"), "xd.line_profile({src}, line_region.vector, line_region.line_width)", "line-profile", [_("Source")], ["src"], [line_var], True)
                info["convert-to-scalar-operation"] = ExpressionInfo(_("Scalar"), "{src}", "convert-to-scalar", [_("Source")], ["src"], list(), True)
                # node-operation
                for data_source_dict in data_source_dicts:
                    operation_dict = data_source_dict.get("data_source")
                    if operation_dict and operation_dict.get("type") == "operation":
                        del data_source_dict["data_source"]
                        operation_id = operation_dict["operation_id"]
                        computation_dict = dict()
                        if operation_id in info:
                            computation_dict["label"] = info[operation_id].label
                            computation_dict["processing_id"] = info[operation_id].processing_id
                            computation_dict["type"] = "computation"
                            computation_dict["uuid"] = str(uuid.uuid4())
                            variables_list = list()
                            data_sources = operation_dict.get("data_sources", list())
                            srcs = ("src", ) if len(data_sources) < 2 else ("src1", "src2")
                            kws = {}
                            for src in srcs:
                                kws[src] = None
                            for i, src_data_source in enumerate(data_sources):
                                kws[srcs[i]] = srcs[i] + (".display_data" if info[operation_id].use_display_data else ".data")
                                if src_data_source.get("type") == "data-item-data-source":
                                    src_uuid = data_source_uuid_to_data_item_uuid.get(src_data_source["buffered_data_source_uuid"], str(uuid.uuid4()))
                                    variable_src = {"label": info[operation_id].src_labels[i], "name": info[operation_id].src_names[i], "type": "variable", "uuid": str(uuid.uuid4())}
                                    variable_src["specifier"] = {"type": "data_item", "uuid": src_uuid, "version": 1}
                                    variables_list.append(variable_src)
                                    if operation_id == "crop-operation":
                                        variable_src = {"label": _("Crop Region"), "name": "crop_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                        variable_src["specifier"] = {"type": "region", "uuid": operation_dict["region_connections"]["crop"], "version": 1}
                                        variables_list.append(variable_src)
                                elif src_data_source.get("type") == "operation":
                                    src_uuid = data_source_uuid_to_data_item_uuid.get(src_data_source["data_sources"][0]["buffered_data_source_uuid"], str(uuid.uuid4()))
                                    variable_src = {"label": info[operation_id].src_labels[i], "name": info[operation_id].src_names[i], "type": "variable", "uuid": str(uuid.uuid4())}
                                    variable_src["specifier"] = {"type": "data_item", "uuid": src_uuid, "version": 1}
                                    variables_list.append(variable_src)
                                    variable_src = {"label": _("Crop Region"), "name": "crop_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                    variable_src["specifier"] = {"type": "region", "uuid": src_data_source["region_connections"]["crop"], "version": 1}
                                    variables_list.append(variable_src)
                                    kws[srcs[i]] = "xd.crop({}, crop_region.bounds)".format(kws[srcs[i]])
                            for rc_k, rc_v in operation_dict.get("region_connections", dict()).items():
                                if rc_k == 'pick':
                                    variable_src = {"name": "pick_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                    variable_src["specifier"] = {"type": "region", "uuid": rc_v, "version": 1}
                                    variables_list.append(variable_src)
                                elif rc_k == 'line':
                                    variable_src = {"name": "line_region", "type": "variable", "uuid": str(uuid.uuid4())}
                                    variable_src["specifier"] = {"type": "region", "uuid": rc_v, "version": 1}
                                    variables_list.append(variable_src)
                            for var in copy.deepcopy(info[operation_id].variables):
                                if var.get("value_type") not in ("line", "point"):
                                    var["uuid"] = str(uuid.uuid4())
                                    var_name = var.get("op_name") or var.get("name")
                                    var["value"] = operation_dict["values"].get(var_name, var.get("value"))
                                    variables_list.append(var)
                            computation_dict["variables"] = variables_list
                            computation_dict["original_expression"] = info[operation_id].expression.format(**kws)
                            data_source_dict["computation"] = computation_dict
                properties["version"] = 9
                logging.getLogger("migration").debug("Updated {} to {} (operation to computation)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v8(reader_info_list):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 7:
                reader_info.changed_ref[0] = True
                # version 7 -> 8 changes metadata to be stored in buffered data source
                data_source_dicts = properties.get("data_sources", list())
                description_metadata = properties.setdefault("metadata", dict()).setdefault("description", dict())
                data_source_dict = dict()
                if len(data_source_dicts) == 1:
                    data_source_dict = data_source_dicts[0]
                    excluded = ["rating", "datetime_original", "title", "source_file_path", "session_id", "caption", "flag", "datetime_modified", "connections", "data_sources", "uuid", "reader_version",
                        "version", "metadata"]
                    for key in list(properties.keys()):
                        if key not in excluded:
                            data_source_dict.setdefault("metadata", dict())[key] = properties[key]
                            del properties[key]
                    for key in ["caption", "title"]:
                        if key in properties:
                            description_metadata[key] = properties[key]
                            del properties[key]
                datetime_original = properties.get("datetime_original", dict())
                dst_value = datetime_original.get("dst", "+00")
                dst_adjust = int(dst_value)
                tz_value = datetime_original.get("tz", "+0000")
                tz_adjust = int(tz_value[0:3]) * 60 + int(tz_value[3:5]) * (-1 if tz_value[0] == '-1' else 1)
                timezone = datetime_original.get("timezone")
                local_datetime = Utility.get_datetime_from_datetime_item(datetime_original)
                if not local_datetime:
                    local_datetime = datetime.datetime.utcnow()
                data_source_dict["created"] = (local_datetime - datetime.timedelta(minutes=dst_adjust + tz_adjust)).isoformat()
                data_source_dict["modified"] = data_source_dict["created"]
                properties["created"] = data_source_dict["created"]
                properties["modified"] = properties["created"]
                time_zone_dict = description_metadata.setdefault("time_zone", dict())
                time_zone_dict["dst"] = dst_value
                time_zone_dict["tz"] = tz_value
                if timezone is not None:
                    time_zone_dict["timezone"] = timezone
                properties.pop("datetime_original", None)
                properties.pop("datetime_modified", None)
                properties["version"] = 8
                logging.getLogger("migration").debug("Updated {} to {} (metadata to data source)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v7(reader_info_list):
    v7lookup = dict()  # map data_item.uuid to buffered data source.uuid
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 6:
                reader_info.changed_ref[0] = True
                # version 6 -> 7 changes data to be cached in the buffered data source object
                buffered_data_source_dict = dict()
                buffered_data_source_dict["type"] = "buffered-data-source"
                buffered_data_source_dict["uuid"] = v7lookup.setdefault(properties["uuid"], str(uuid.uuid4()))  # assign a new uuid
                include_data = "master_data_shape" in properties and "master_data_dtype" in properties
                data_shape = properties.get("master_data_shape")
                data_dtype = properties.get("master_data_dtype")
                if "intensity_calibration" in properties:
                    buffered_data_source_dict["intensity_calibration"] = properties["intensity_calibration"]
                    del properties["intensity_calibration"]
                if "dimensional_calibrations" in properties:
                    buffered_data_source_dict["dimensional_calibrations"] = properties["dimensional_calibrations"]
                    del properties["dimensional_calibrations"]
                if "master_data_shape" in properties:
                    buffered_data_source_dict["data_shape"] = data_shape
                    del properties["master_data_shape"]
                if "master_data_dtype" in properties:
                    buffered_data_source_dict["data_dtype"] = data_dtype
                    del properties["master_data_dtype"]
                if "displays" in properties:
                    buffered_data_source_dict["displays"] = properties["displays"]
                    del properties["displays"]
                if "regions" in properties:
                    buffered_data_source_dict["regions"] = properties["regions"]
                    del properties["regions"]
                operation_dict = properties.pop("operation", None)
                if operation_dict is not None:
                    buffered_data_source_dict["data_source"] = operation_dict
                    for data_source_dict in operation_dict.get("data_sources", dict()):
                        data_source_dict["buffered_data_source_uuid"] = v7lookup.setdefault(data_source_dict["data_item_uuid"], str(uuid.uuid4()))
                        data_source_dict.pop("data_item_uuid", None)
                if include_data or operation_dict is not None:
                    properties["data_sources"] = [buffered_data_source_dict]
                properties["version"] = 7
                logging.getLogger("migration").debug("Updated {} to {} (buffered data sources)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v6(reader_info_list):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 5:
                reader_info.changed_ref[0] = True
                # version 5 -> 6 changes operations to a single operation, expands data sources list
                operations_list = properties.get("operations", list())
                if len(operations_list) == 1:
                    operation_dict = operations_list[0]
                    operation_dict["type"] = "operation"
                    properties["operation"] = operation_dict
                    data_sources_list = properties.get("data_sources", list())
                    if len(data_sources_list) > 0:
                        new_data_sources_list = list()
                        for data_source_uuid_str in data_sources_list:
                            new_data_sources_list.append({"type": "data-item-data-source", "data_item_uuid": data_source_uuid_str})
                        operation_dict["data_sources"] = new_data_sources_list
                if "operations" in properties:
                    del properties["operations"]
                if "data_sources" in properties:
                    del properties["data_sources"]
                if "intrinsic_intensity_calibration" in properties:
                    properties["intensity_calibration"] = properties["intrinsic_intensity_calibration"]
                    del properties["intrinsic_intensity_calibration"]
                if "intrinsic_spatial_calibrations" in properties:
                    properties["dimensional_calibrations"] = properties["intrinsic_spatial_calibrations"]
                    del properties["intrinsic_spatial_calibrations"]
                properties["version"] = 6
                logging.getLogger("migration").debug("Updated {} to {} (operation hierarchy)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v5(reader_info_list):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 4:
                reader_info.changed_ref[0] = True
                # version 4 -> 5 changes region_uuid to region_connections map.
                operations_list = properties.get("operations", list())
                for operation_dict in operations_list:
                    if operation_dict["operation_id"] == "crop-operation" and "region_uuid" in operation_dict:
                        operation_dict["region_connections"] = {"crop": operation_dict["region_uuid"]}
                        del operation_dict["region_uuid"]
                    elif operation_dict["operation_id"] == "line-profile-operation" and "region_uuid" in operation_dict:
                        operation_dict["region_connections"] = {"line": operation_dict["region_uuid"]}
                        del operation_dict["region_uuid"]
                properties["version"] = 5
                logging.getLogger("migration").debug("Updated {} to {} (region_uuid)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v4(reader_info_list):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 3:
                reader_info.changed_ref[0] = True
                # version 3 -> 4 changes origin to offset in all calibrations.
                calibration_dict = properties.get("intrinsic_intensity_calibration", dict())
                if "origin" in calibration_dict:
                    calibration_dict["offset"] = calibration_dict["origin"]
                    del calibration_dict["origin"]
                for calibration_dict in properties.get("intrinsic_spatial_calibrations", list()):
                    if "origin" in calibration_dict:
                        calibration_dict["offset"] = calibration_dict["origin"]
                        del calibration_dict["origin"]
                properties["version"] = 4
                logging.getLogger("migration").debug("Updated {} to {} (calibration offset)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v3(reader_info_list):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version == 2:
                reader_info.changed_ref[0] = True
                # version 2 -> 3 adds uuid's to displays, graphics, and operations. regions already have uuids.
                for display_properties in properties.get("displays", list()):
                    display_properties.setdefault("uuid", str(uuid.uuid4()))
                    for graphic_properties in display_properties.get("graphics", list()):
                        graphic_properties.setdefault("uuid", str(uuid.uuid4()))
                for operation_properties in properties.get("operations", list()):
                    operation_properties.setdefault("uuid", str(uuid.uuid4()))
                properties["version"] = 3
                logging.getLogger("migration").debug("Updated {} to {} (add uuids)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v2(reader_info_list):
    for reader_info in reader_info_list:
        storage_handler = reader_info.storage_handler
        properties = reader_info.properties
        try:
            version = properties.get("version", 0)
            if version <= 1:
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
                temp_data = storage_handler.read_data()
                if temp_data is not None:
                    properties["master_data_dtype"] = str(temp_data.dtype)
                    properties["master_data_shape"] = temp_data.shape
                properties["displays"] = [{}]
                properties["uuid"] = properties.get("uuid", str(uuid.uuid4()))  # assign a new uuid if it doesn't exist
                properties["version"] = 2
                logging.getLogger("migration").debug("Updated {} to {} (ndata1)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()


def migrate_library_to_v2(library_properties):
    if library_properties.get("version", 0) < 2:
        for data_group_properties in library_properties.get("data_groups", list()):
            data_group_properties.pop("data_groups")
            display_item_references = data_group_properties.setdefault("display_item_references", list())
            data_item_uuid_strs = data_group_properties.pop("data_item_uuids", list())
            for data_item_uuid_str in data_item_uuid_strs:
                for display_item_properties in library_properties.get("display_items", list()):
                    data_item_references = [d.get("data_item_reference", None) for d in
                                            display_item_properties.get("display_data_channels", list())]
                    if data_item_uuid_str in data_item_references:
                        display_item_references.append(display_item_properties["uuid"])
        data_item_uuid_to_display_item_uuid_map = dict()
        data_item_uuid_to_display_item_dict_map = dict()
        display_to_display_item_map = dict()
        display_to_display_data_channel_map = dict()
        for display_item_properties in library_properties.get("display_items", list()):
            display_to_display_item_map[display_item_properties["display"]["uuid"]] = display_item_properties["uuid"]
            display_to_display_data_channel_map[display_item_properties["display"]["uuid"]] = \
            display_item_properties["display_data_channels"][0]["uuid"]
            data_item_references = [d.get("data_item_reference", None) for d in
                                    display_item_properties.get("display_data_channels", list())]
            for data_item_uuid_str in data_item_references:
                data_item_uuid_to_display_item_uuid_map.setdefault(data_item_uuid_str, display_item_properties["uuid"])
                data_item_uuid_to_display_item_dict_map.setdefault(data_item_uuid_str, display_item_properties)
            display_item_properties.pop("display", None)
        for workspace_properties in library_properties.get("workspaces", list()):
            def replace1(d):
                if "children" in d:
                    for dd in d["children"]:
                        replace1(dd)
                if "data_item_uuid" in d:
                    data_item_uuid_str = d.pop("data_item_uuid")
                    display_item_uuid_str = data_item_uuid_to_display_item_uuid_map.get(data_item_uuid_str)
                    if display_item_uuid_str:
                        d["display_item_uuid"] = display_item_uuid_str

            replace1(workspace_properties["layout"])
        for connection_dict in library_properties.get("connections", list()):
            source_uuid_str = connection_dict["source_uuid"]
            if connection_dict["type"] == "interval-list-connection":
                connection_dict["source_uuid"] = display_to_display_item_map.get(source_uuid_str, None)
            if connection_dict["type"] == "property-connection" and connection_dict[
                "source_property"] == "slice_interval":
                connection_dict["source_uuid"] = display_to_display_data_channel_map.get(source_uuid_str, None)

        def fix_specifier(specifier_dict):
            if specifier_dict.get("type") in (
            "data_item", "display_xdata", "cropped_xdata", "cropped_display_xdata", "filter_xdata", "filtered_xdata"):
                if specifier_dict.get("uuid") in data_item_uuid_to_display_item_dict_map:
                    specifier_dict["uuid"] = \
                    data_item_uuid_to_display_item_dict_map[specifier_dict["uuid"]]["display_data_channels"][0]["uuid"]
                else:
                    specifier_dict.pop("uuid", None)
            if specifier_dict.get("type") == "data_item":
                specifier_dict["type"] = "data_source"
            if specifier_dict.get("type") == "data_item_object":
                specifier_dict["type"] = "data_item"
            if specifier_dict.get("type") == "region":
                specifier_dict["type"] = "graphic"

        for computation_dict in library_properties.get("computations", list()):
            for variable_dict in computation_dict.get("variables", list()):
                if "specifier" in variable_dict:
                    specifier_dict = variable_dict["specifier"]
                    if specifier_dict is not None:
                        fix_specifier(specifier_dict)
                if "secondary_specifier" in variable_dict:
                    specifier_dict = variable_dict["secondary_specifier"]
                    if specifier_dict is not None:
                        fix_specifier(specifier_dict)
            for result_dict in computation_dict.get("results", list()):
                fix_specifier(result_dict["specifier"])
        library_properties["version"] = 2
        logging.getLogger("migration").debug("Updated 1 to 2 (display items)")

def migrate_library_to_v3(library_properties):
    if library_properties.get("version", 0) == 2:
        library_properties.pop("workspaces", None)
        library_properties.pop("data_groups", None)
        library_properties.pop("workspace_uuid", None)
        library_properties.pop("data_item_references", None)
        library_properties.pop("data_item_variables", None)
        library_properties["version"] = 3
        logging.getLogger("migration").debug("Updated 2 to 3 (profiles)")
