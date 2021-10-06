import typing

# standardized metadata paths, mapping to properties

session_key_map = {
    'stem.session.site': {'paths': ['site'], 'type': 'string'},
    'stem.session.instrument': {'paths': ['instrument'], 'type': 'string'},
    'stem.session.detector': {'paths': ['detector'], 'type': 'string'},
    'stem.session.task': {'paths': ['task'], 'type': 'string'},
    'stem.session.microscopist': {'paths': ['microscopist'], 'type': 'string'},
    'stem.session.sample': {'paths': ['sample'], 'type': 'string'},
    'stem.session.sample_area': {'paths': ['sample_area'], 'type': 'string'},
    'stem.session.sample_source': {'paths': ['sample_source'], 'type': 'string'},
    'stem.session.sample_formula': {'paths': ['sample_formula'], 'type': 'string'},
}

# 'hardware_source' should be 'detector' at some point in the future. see HMSA file format for more thoughts.

# keys can exclude the unit suffix if units are SI

key_map = {
    # the info about the primary detector
    'stem.hardware_source.id': {'paths': ['hardware_source.hardware_source_id'], 'type': 'string'},
    'stem.hardware_source.name': {'paths': ['hardware_source.hardware_source_name'], 'type': 'string'},
    'stem.hardware_source.frame_number': {'paths': ['hardware_source.frame_number'], 'type': 'int'},
    'stem.hardware_source.valid_rows': {'paths': ['hardware_source.valid_rows'], 'type': 'int'},

    'stem.signal_type': {'paths': ['hardware_source.signal_type'], 'type': 'string'},
    # EDXS, WDS, ELS, AES, PES, XRF, CLS, GAM, BEI, CBED, EBSD, EDIF, LEED, OPR, OPT, PIXE, RHEED, SEI, SXES, TEM
    # see HMSA

    'stem.high_tension': {'paths': ['instrument.high_tension',
                                    'hardware_source.autostem.high_tension_v'], 'type': 'integer'},
    'stem.high_tension_v': {'paths': ['instrument.high_tension',
                                    'hardware_source.autostem.high_tension_v'], 'type': 'integer'},
    'stem.gun_type': {'paths': ['instrument.gun_type', 'hardware_source.gun_type'], 'type': 'string'},
    'stem.convergence_angle': {'paths': ['instrument.convergence_angle',
                                         'hardware_source.convergence_angle_rad'], 'type': 'real'},
    'stem.convergence_angle_rad': {'paths': ['instrument.convergence_angle',
                                         'hardware_source.convergence_angle_rad'], 'type': 'real'},
    'stem.collection_angle': {'paths': ['instrument.collection_angle',
                                        'hardware_source.collection_angle_rad'], 'type': 'real'},
    'stem.collection_angle_rad': {'paths': ['instrument.collection_angle',
                                        'hardware_source.collection_angle_rad'], 'type': 'real'},
    'stem.probe_size': {'paths': ['instrument.probe_size', 'hardware_source.probe_size_m2'], 'type': 'real'},
    'stem.probe_size_m2': {'paths': ['instrument.probe_size', 'hardware_source.probe_size_m2'], 'type': 'real'},
    'stem.beam_current': {'paths': ['instrument.beam_current', 'hardware_source.beam_current_a'], 'type': 'real'},
    'stem.beam_current_a': {'paths': ['instrument.beam_current', 'hardware_source.beam_current_a'], 'type': 'real'},
    'stem.defocus': {'paths': ['instrument.defocus', 'hardware_source.defocus_m'], 'type': 'real'},
    'stem.defocus_m': {'paths': ['instrument.defocus', 'hardware_source.defocus_m'], 'type': 'real'},

    'stem.eels.spectrum_type': {'paths': ['hardware_source.eels_spectrum_type'], 'type': 'string'},
    'stem.eels.resolution_eV': {'paths': ['hardware_source.eels_resolution_eV'], 'type': 'string'},
    'stem.eels.is_monochromated': {'paths': ['hardware_source.eels_is_monochromated'], 'type': 'boolean'},

    'stem.camera.binning': {'paths': ['hardware_source.binning'], 'type': 'integer'},
    'stem.camera.channel_id': {'paths': ['hardware_source.channel_id'], 'type': 'string'},
    'stem.camera.channel_index': {'paths': ['hardware_source.channel_index'], 'type': 'integer'},
    'stem.camera.channel_name': {'paths': ['hardware_source.channel_name'], 'type': 'string'},
    'stem.camera.exposure': {'paths': ['hardware_source.exposure'], 'type': 'real'},
    'stem.camera.exposure_s': {'paths': ['hardware_source.exposure'], 'type': 'real'},
    'stem.camera.frame_index': {'paths': ['hardware_source.frame_index'], 'type': 'integer'},
    'stem.camera.frame_number': {'paths': ['hardware_source.frame_number'], 'type': 'integer'},
    'stem.camera.valid_rows': {'paths': ['hardware_source.valid_rows'], 'type': 'integer'},
    'stem.camera.detector_current': {'paths': ['hardware_source.detector_current'], 'type': 'real'},

    'stem.scan.center_x_nm': {'paths': ['scan.center_x_nm', 'hardware_source.center_x_nm'], 'type': 'real'},
    'stem.scan.center_y_nm': {'paths': ['scan.center_y_nm', 'hardware_source.center_y_nm'], 'type': 'real'},
    'stem.scan.fov_nm': {'paths': ['scan.fov_nm', 'hardware_source.fov_nm'], 'type': 'real'},
    'stem.scan.rotation': {'paths': ['scan.rotation', 'hardware_source.rotation'], 'type': 'real'},
    'stem.scan.rotation_rad': {'paths': ['scan.rotation', 'hardware_source.rotation'], 'type': 'real'},
    'stem.scan.scan_id': {'paths': ['scan.scan_id', 'hardware_source.scan_id'], 'type': 'string'},
    'stem.scan.valid_rows': {'paths': ['scan.valid_rows', 'hardware_source.valid_rows'], 'type': 'integer'},

    'stem.scan.channel_id': {'paths': ['hardware_source.channel_id'], 'type': 'string'},
    'stem.scan.channel_index': {'paths': ['hardware_source.channel_index'], 'type': 'integer'},
    'stem.scan.channel_name': {'paths': ['hardware_source.channel_name'], 'type': 'string'},
    'stem.scan.frame_time': {'paths': ['hardware_source.exposure'], 'type': 'real'},
    'stem.scan.frame_time_s': {'paths': ['hardware_source.exposure'], 'type': 'real'},
    'stem.scan.frame_index': {'paths': ['hardware_source.frame_index'], 'type': 'integer'},
    'stem.scan.pixel_time_us': {'paths': ['hardware_source.pixel_time_us'], 'type': 'real'},
    'stem.scan.line_time_us': {'paths': ['hardware_source.line_time_us'], 'type': 'real'},
}


def has_metadata_value(metadata_source: typing.Any, key: str) -> bool:
    """Return whether the metadata value for the given key exists.

    There are a set of predefined keys that, when used, will be type checked and be interoperable with other
    applications. Please consult reference documentation for valid keys.

    If using a custom key, we recommend structuring your keys in the '<group>.<attribute>' format followed
    by the predefined keys. e.g. 'session.instrument' or 'camera.binning'.

    Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
    using the ``metadata_value`` methods over directly accessing ``metadata``.
    """
    desc = session_key_map.get(key)
    if desc is not None:
        d = getattr(metadata_source, "session_metadata", metadata_source)
        for path in desc["paths"]:
            path_components = path.split(".")
            for k in path_components[:-1]:
                d =  d.get(k, dict()) if d is not None else None
            if d is not None:
                return path_components[-1] in d
    desc = key_map.get(key)
    if desc is not None:
        d = getattr(metadata_source, "metadata", metadata_source)
        for path in desc["paths"]:
            path_components = path.split(".")
            for k in path_components[:-1]:
                d =  d.get(k, dict()) if d is not None else None
            if d is not None:
                return path_components[-1] in d
    return False


def get_metadata_value(metadata_source: typing.Any, key: str) -> typing.Any:
    """Get the metadata value for the given key.

    There are a set of predefined keys that, when used, will be type checked and be interoperable with other
    applications. Please consult reference documentation for valid keys.

    If using a custom key, we recommend structuring your keys in the '<group>.<attribute>' format followed
    by the predefined keys. e.g. 'session.instrument' or 'camera.binning'.

    Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
    using the ``metadata_value`` methods over directly accessing ``metadata``.
    """
    desc = session_key_map.get(key)
    if desc is not None:
        for path in desc["paths"]:
            v = getattr(metadata_source, "session_metadata", metadata_source)
            path_components = path.split(".")
            for k in path_components:
                v =  v.get(k) if v is not None else None
            if v is not None:
                return v
    desc = key_map.get(key)
    if desc is not None:
        v = getattr(metadata_source, "metadata", metadata_source)
        for path in desc["paths"]:
            path_components = path.split(".")
            for k in path_components:
                v =  v.get(k) if v is not None else None
            if v is not None:
                return v
    return None


def set_metadata_value(metadata_source: typing.Any, key: str, value: typing.Any) -> None:
    """Set the metadata value for the given key.

    There are a set of predefined keys that, when used, will be type checked and be interoperable with other
    applications. Please consult reference documentation for valid keys.

    If using a custom key, we recommend structuring your keys in the '<group>.<attribute>' format followed
    by the predefined keys. e.g. 'session.instrument' or 'camera.binning'.

    Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
    using the ``metadata_value`` methods over directly accessing ``metadata``.
    """
    desc = session_key_map.get(key)
    if desc is not None:
        d0 = getattr(metadata_source, "session_metadata", metadata_source)
        d = d0
        path = desc["paths"][0]
        path_components = path.split(".")
        for k in path_components[:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None:
            d[path_components[-1]] = value
            metadata_source.session_metadata = d0
            return
    desc = key_map.get(key)
    if desc is not None:
        d0 = getattr(metadata_source, "metadata", metadata_source)
        d = d0
        path = desc["paths"][0]
        path_components = path.split(".")
        for k in path_components[:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None:
            d[path_components[-1]] = value
            metadata_source.metadata = d0
            return
    raise KeyError()


def delete_metadata_value(metadata_source: typing.Any, key: str) -> None:
    """Delete the metadata value for the given key.

    There are a set of predefined keys that, when used, will be type checked and be interoperable with other
    applications. Please consult reference documentation for valid keys.

    If using a custom key, we recommend structuring your keys in the '<dotted>.<group>.<attribute>' format followed
    by the predefined keys. e.g. 'stem.session.instrument' or 'stm.camera.binning'.

    Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
    using the ``metadata_value`` methods over directly accessing ``metadata``.
    """
    desc = session_key_map.get(key)
    if desc is not None:
        d0 = getattr(metadata_source, "session_metadata", dict())
        changed = False
        for path in desc["paths"]:
            d = d0
            path_components = path.split(".")
            for k in path_components[:-1]:
                d =  d.setdefault(k, dict()) if d is not None else None
            if d is not None and path_components[-1] in d:
                d.pop(path_components[-1], None)
                changed = True
        if changed:
            metadata_source.session_metadata = d0
    desc = key_map.get(key)
    if desc is not None:
        d0 = getattr(metadata_source, "metadata", dict())
        changed = False
        for path in desc["paths"]:
            d = d0
            path_components = path.split(".")
            for k in path_components[:-1]:
                d =  d.setdefault(k, dict()) if d is not None else None
            if d is not None and path_components[-1] in d:
                d.pop(path_components[-1], None)
                metadata_source.metadata = d0
                changed = True
        if changed:
            metadata_source.session_metadata = d0
