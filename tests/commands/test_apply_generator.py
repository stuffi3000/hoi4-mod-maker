"""ApplyGeneratorCommand test - full image/mask writing and undoing, in-place modification to maintain aliases."""

from types import SimpleNamespace

import numpy as np
import pytest

from commands.map.apply_generator import ApplyGeneratorCommand


def _md():
    return SimpleNamespace(height_map=np.full((8, 8), 50, dtype=np.uint8))


def test_full_apply_and_undo():
    md = _md()
    alias = md.height_map                       # Simulate the alias held by the canvas
    new = np.full((8, 8), 200, dtype=np.uint8)

    cmd = ApplyGeneratorCommand(md, "height_map", new, label="Test generation")
    cmd.execute()
    assert np.all(md.height_map == 200)
    assert alias is md.height_map               # Write in place, aliases continue

    cmd.undo()
    assert np.all(md.height_map == 50)
    assert cmd.label == "Test generation"


def test_masked_apply_and_undo():
    md = _md()
    new = np.full((8, 8), 200, dtype=np.uint8)
    mask = np.zeros((8, 8), dtype=bool)
    mask[:4] = True

    cmd = ApplyGeneratorCommand(md, "height_map", new, mask=mask)
    cmd.execute()
    assert np.all(md.height_map[:4] == 200)
    assert np.all(md.height_map[4:] == 50)

    cmd.undo()
    assert np.all(md.height_map == 50)


def test_wrong_layer_name_fails_loudly():
    """If the layer name is written incorrectly, it must be exploded on the spot, and cannot take effect quietly."""
    with pytest.raises(AttributeError):
        ApplyGeneratorCommand(_md(), "hieght_map",
                              np.zeros((8, 8), dtype=np.uint8))
