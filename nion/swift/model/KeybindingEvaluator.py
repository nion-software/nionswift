from nion.ui import UserInterface

class KeybindingEvaluator:
    def __init__(self, key_config: dict):
        self.key_config = key_config

    def is_key_mode_enabled(
        self,
        modifiers: UserInterface.KeyboardModifiers,
        key: str,
        mode_name: str
    ) -> bool:
        key = key.lower()
        mode_name = mode_name.lower()

        for category, bindings in self.key_config.items():
            for binding in bindings:
                if mode_name not in binding["description"].lower():
                    continue
                key_options = self.expand_key_combos(binding["key"])
                if any(self._modifiers_match(combo, modifiers, key) for combo in key_options):
                    return True
        return False

    def expand_key_combos(self, key_str: str) -> list[str]:
        parts = [part.strip() for part in key_str.split("/")]
        combos = [" + ".join([p.strip().capitalize() for p in part.split("+")]) for part in parts]
        return combos

    def _modifiers_match(self, combo_str: str, modifiers: UserInterface.KeyboardModifiers, key: str) -> bool:
        combo_parts = [p.strip().lower() for p in combo_str.split("+")]
        wants_ctrl = "ctrl" in combo_parts
        wants_shift = "shift" in combo_parts
        wants_alt = "alt" in combo_parts
        expected_keys = [p for p in combo_parts if p not in ("ctrl", "shift", "alt")]
        if not expected_keys:
            return False
        if modifiers.control != wants_ctrl:
            return False
        if modifiers.shift != wants_shift:
            return False
        if modifiers.alt != wants_alt:
            return False

        return key.lower() in expected_keys