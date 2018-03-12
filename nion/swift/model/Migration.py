import collections
import copy
import datetime
import gettext
import logging
import uuid

from nion.swift.model import Utility

_ = gettext.gettext


class MigrationLog:
    def __init__(self, enabled: bool):
        self.__enabled = enabled

    def push(self, entry: str) -> None:
        if self.__enabled:
            logging.info(entry)

def migrate_to_latest(reader_info_list, library_updates, migration_log: MigrationLog) -> None:
    migrate_to_v2(reader_info_list, migration_log)
    migrate_to_v3(reader_info_list, migration_log)
    migrate_to_v4(reader_info_list, migration_log)
    migrate_to_v5(reader_info_list, migration_log)
    migrate_to_v6(reader_info_list, migration_log)
    migrate_to_v7(reader_info_list, migration_log)
    migrate_to_v8(reader_info_list, migration_log)
    migrate_to_v9(reader_info_list, migration_log)
    migrate_to_v10(reader_info_list, migration_log)
    migrate_to_v11(reader_info_list, migration_log)
    migrate_to_v12(reader_info_list, library_updates, migration_log)
    # TODO: library item should have a 'type' so that the correct class can be reconstructed
    # TODO: file format. rename specifier types (data_item -> data_source, library_item -> data_item, region -> graphic)
    # TODO: file format. switch from 'displays' to a single 'display' in data item
    # TODO: file format. Rename workspaces to workspace_layouts.

def migrate_to_v12(reader_info_list, library_updates, migration_log: MigrationLog):
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

                migration_log.push("Updated {} to {} (move connections/computations to library)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v11(reader_info_list, migration_log: MigrationLog):
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

                migration_log.push("Updated {} to {} (computed data items combined crop, data source merge)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v10(reader_info_list, migration_log: MigrationLog):
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
                migration_log.push("Updated {} to {} (regions merged into graphics)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v9(reader_info_list, migration_log: MigrationLog):
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
                migration_log.push("Updated {} to {} (operation to computation)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v8(reader_info_list, migration_log: MigrationLog):
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
                    for key in ["caption", "flag", "rating", "title"]:
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
                migration_log.push("Updated {} to {} (metadata to data source)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v7(reader_info_list, migration_log: MigrationLog):
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
                migration_log.push("Updated {} to {} (buffered data sources)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v6(reader_info_list, migration_log: MigrationLog):
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
                migration_log.push("Updated {} to {} (operation hierarchy)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v5(reader_info_list, migration_log: MigrationLog):
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
                migration_log.push("Updated {} to {} (region_uuid)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v4(reader_info_list, migration_log: MigrationLog):
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
                migration_log.push("Updated {} to {} (calibration offset)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v3(reader_info_list, migration_log: MigrationLog):
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
                migration_log.push("Updated {} to {} (add uuids)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()

def migrate_to_v2(reader_info_list, migration_log: MigrationLog):
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
                properties["uuid"] = str(uuid.uuid4())  # assign a new uuid
                properties["version"] = 2
                migration_log.push("Updated {} to {} (ndata1)".format(storage_handler.reference, properties["version"]))
        except Exception as e:
            logging.debug("Error reading %s", storage_handler.reference)
            import traceback
            traceback.print_exc()
            traceback.print_stack()
