import typing

# standardized metadata paths, mapping to properties

session_key_map = {
    'stem.session.site': {'path': ['site'], 'type': 'string'},
    'stem.session.instrument': {'path': ['instrument'], 'type': 'string'},
    'stem.session.detector': {'path': ['detector'], 'type': 'string'},
    'stem.session.task': {'path': ['task'], 'type': 'string'},
    'stem.session.microscopist': {'path': ['microscopist'], 'type': 'string'},
    'stem.session.sample': {'path': ['sample'], 'type': 'string'},
    'stem.session.sample_area': {'path': ['sample_area'], 'type': 'string'},
    'stem.session.sample_source': {'path': ['sample_source'], 'type': 'string'},
    'stem.session.sample_formula': {'path': ['sample_formula'], 'type': 'string'},
}

# 'hardware_source' should be 'detector' at some point in the future. see HMSA file format for more thoughts.

# keys can exclude the unit suffix if units are SI

key_map = {
    'stem.hardware_source.id': {'path': ['hardware_source', 'hardware_source_id'], 'type': 'string'},
    'stem.hardware_source.name': {'path': ['hardware_source', 'hardware_source_name'], 'type': 'string'},

    'stem.signal_type': {'path': ['hardware_source', 'signal_type'], 'type': 'string'},
    # EDS, WDS, ELS, AES, PES, XRF, CLS, GAM, BEI, CBED, EBSD, EDIF, LEED, OPR, OPT, PIXE, RHEED, SEI, SXES, TEM
    # see HMSA

    'stem.high_tension_v': {'path': ['hardware_source', 'autostem', 'high_tension_v'], 'type': 'integer'},
    'stem.gun_type': {'path': ['hardware_source', 'gun_type'], 'type': 'string'},
    'stem.convergence_angle_rad': {'path': ['hardware_source', 'convergence_angle_rad'], 'type': 'real'},
    'stem.collection_angle_rad': {'path': ['hardware_source', 'collection_angle_rad'], 'type': 'real'},
    'stem.probe_size_m2': {'path': ['hardware_source', 'probe_size_m2'], 'type': 'real'},
    'stem.beam_current_a': {'path': ['hardware_source', 'beam_current_a'], 'type': 'real'},
    'stem.defocus_m': {'path': ['hardware_source', 'defocus_m'], 'type': 'real'},

    'stem.eels.spectrum_type': {'path': ['hardware_source', 'eels_spectrum_type'], 'type': 'string'},
    'stem.eels.resolution_eV': {'path': ['hardware_source', 'eels_resolution_eV'], 'type': 'string'},
    'stem.eels.is_monochromated': {'path': ['hardware_source', 'eels_is_monochromated'], 'type': 'boolean'},

    'stem.camera.binning': {'path': ['hardware_source', 'binning'], 'type': 'integer'},
    'stem.camera.channel_id': {'path': ['hardware_source', 'channel_id'], 'type': 'string'},
    'stem.camera.channel_index': {'path': ['hardware_source', 'channel_index'], 'type': 'integer'},
    'stem.camera.channel_name': {'path': ['hardware_source', 'channel_name'], 'type': 'string'},
    'stem.camera.exposure_s': {'path': ['hardware_source', 'exposure'], 'type': 'real'},
    'stem.camera.frame_index': {'path': ['hardware_source', 'frame_index'], 'type': 'integer'},
    'stem.camera.valid_rows': {'path': ['hardware_source', 'valid_rows'], 'type': 'integer'},
    'stem.camera.detector_current': {'path': ['hardware_source', 'detector_current'], 'type': 'real'},

    'stem.scan.center_x_nm': {'path': ['hardware_source', 'center_x_nm'], 'type': 'real'},
    'stem.scan.center_y_nm': {'path': ['hardware_source', 'center_y_nm'], 'type': 'real'},
    'stem.scan.channel_id': {'path': ['hardware_source', 'channel_id'], 'type': 'string'},
    'stem.scan.channel_index': {'path': ['hardware_source', 'channel_index'], 'type': 'integer'},
    'stem.scan.channel_name': {'path': ['hardware_source', 'channel_name'], 'type': 'string'},
    'stem.scan.frame_time_s': {'path': ['hardware_source', 'exposure'], 'type': 'real'},
    'stem.scan.fov_nm': {'path': ['hardware_source', 'fov_nm'], 'type': 'real'},
    'stem.scan.frame_index': {'path': ['hardware_source', 'frame_index'], 'type': 'integer'},
    'stem.scan.pixel_time_us': {'path': ['hardware_source', 'pixel_time_us'], 'type': 'real'},
    'stem.scan.rotation_rad': {'path': ['hardware_source', 'rotation_rad'], 'type': 'real'},
    'stem.scan.scan_id': {'path': ['hardware_source', 'scan_id'], 'type': 'string'},
    'stem.scan.valid_rows': {'path': ['hardware_source', 'valid_rows'], 'type': 'integer'},
    'stem.scan.line_time_us': {'path': ['hardware_source', 'line_time_us'], 'type': 'real'},
}


def has_metadata_value(metadata_source, key: str) -> bool:
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
        d = getattr(metadata_source, "session_metadata", dict())
        for k in desc['path'][:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None:
            return desc['path'][-1] in d
    desc = key_map.get(key)
    if desc is not None:
        d = getattr(metadata_source, "metadata", dict())
        for k in desc['path'][:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None:
            return desc['path'][-1] in d
    raise False

def get_metadata_value(metadata_source, key: str) -> typing.Any:
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
        v = getattr(metadata_source, "session_metadata", dict())
        for k in desc['path']:
            v =  v.get(k) if v is not None else None
        return v
    desc = key_map.get(key)
    if desc is not None:
        v = getattr(metadata_source, "metadata", dict())
        for k in desc['path']:
            v =  v.get(k) if v is not None else None
        return v
    raise KeyError()

def set_metadata_value(metadata_source, key: str, value: typing.Any) -> None:
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
        d0 = getattr(metadata_source, "session_metadata", dict())
        d = d0
        for k in desc['path'][:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None:
            d[desc['path'][-1]] = value
            metadata_source.session_metadata = d0
            return
    desc = key_map.get(key)
    if desc is not None:
        d0 = getattr(metadata_source, "metadata", dict())
        d = d0
        for k in desc['path'][:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None:
            d[desc['path'][-1]] = value
            metadata_source.metadata = d0
            return
    raise KeyError()

def delete_metadata_value(metadata_source, key: str) -> None:
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
        d = d0
        for k in desc['path'][:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None and desc['path'][-1] in d:
            d.pop(desc['path'][-1], None)
            metadata_source.session_metadata = d0
            return
    desc = key_map.get(key)
    if desc is not None:
        d0 = getattr(metadata_source, "metadata", dict())
        d = d0
        for k in desc['path'][:-1]:
            d =  d.setdefault(k, dict()) if d is not None else None
        if d is not None and desc['path'][-1] in d:
            d.pop(desc['path'][-1], None)
            metadata_source.metadata = d0
            return
