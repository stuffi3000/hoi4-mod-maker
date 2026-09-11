"""Pure NumPy 2D Perlin noise generator.

Boundary perturbation and scatter effects for automatic terrain generation.
No external dependencies, fully vectorized operations."""

import numpy as np


def _fade(t: np.ndarray) -> np.ndarray:
    """Improved Perlin fade: 6t^5 - 15t^4 + 10t^3"""
    return t * t * t * (t * (t * 6 - 15) + 10)


def _lerp(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    return a + t * (b - a)


def perlin_2d(
    shape: tuple[int, int],
    scale: float = 64.0,
    octaves: int = 4,
    persistence: float = 0.5,
    seed: int = 0,
    downsample: int = 0,
) -> np.ndarray:
    """Generate 2D Perlin noise.

    Parameters
    ----------
    shape: (height, width)
    scale: noise scale, the larger the noise, the smoother it will be
    octaves: number of overlays
    persistence: amplitude attenuation for each layer
    seed: random seed
    downsample: When >0, first generate at 1/downsample resolution and then enlarge by bilinear interpolation (accelerate large image)

    Returns
    -------
    float32 array, shape=shape, value range approximately [-1, 1]"""
    if downsample > 1:
        small_h = max(1, shape[0] // downsample)
        small_w = max(1, shape[1] // downsample)
        small = _perlin_multi((small_h, small_w), scale / downsample, octaves, persistence, seed)
        from scipy.ndimage import zoom
        result = zoom(small, (shape[0] / small_h, shape[1] / small_w), order=1)
        return result.astype(np.float32)

    return _perlin_multi(shape, scale, octaves, persistence, seed)


def _perlin_multi(
    shape: tuple[int, int],
    scale: float,
    octaves: int,
    persistence: float,
    seed: int,
) -> np.ndarray:
    """Multilayer Perlin noise."""
    result = np.zeros(shape, dtype=np.float32)
    amplitude = 1.0
    max_amplitude = 0.0

    for octave in range(octaves):
        freq = 2 ** octave
        oct_scale = scale / freq
        result += amplitude * _perlin_single(shape, oct_scale, seed + octave * 1000)
        max_amplitude += amplitude
        amplitude *= persistence

    result /= max_amplitude
    return result


def _perlin_single(
    shape: tuple[int, int],
    scale: float,
    seed: int,
) -> np.ndarray:
    """Single layer Perlin noise (vectorized)."""
    h, w = shape
    rng = np.random.default_rng(seed)

    # Grid coordinates
    grid_h = int(np.ceil(h / scale)) + 2
    grid_w = int(np.ceil(w / scale)) + 2

    # stochastic gradient (angle → unit vector)
    angles = rng.uniform(0, 2 * np.pi, (grid_h, grid_w)).astype(np.float32)
    grad_x = np.cos(angles)
    grad_y = np.sin(angles)

    # pixel coordinate → grid coordinate
    ys = np.arange(h, dtype=np.float32) / scale
    xs = np.arange(w, dtype=np.float32) / scale

    # grid integer coordinates
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)

    # decimal part
    dy = ys - y0.astype(np.float32)
    dx = xs - x0.astype(np.float32)

    # fade curve
    fy = _fade(dy)
    fx = _fade(dx)

    # Gradient dot product of four corners (vectorized, using broadcasting)
    # shape: (h, w)
    y0_2d = y0[:, None]  # (h, 1)
    x0_2d = x0[None, :]  # (1, w)
    dy_2d = dy[:, None]  # (h, 1)
    dx_2d = dx[None, :]  # (1, w)

    def dot_grid(gy, gx):
        """Computes the dot product of gradient and distance vectors."""
        return (grad_x[gy, gx] * dx_2d + grad_y[gy, gx] * dy_2d)

    # Limit index range
    y1 = np.minimum(y0 + 1, grid_h - 1)
    x1 = np.minimum(x0 + 1, grid_w - 1)

    y0_2d_arr = y0[:, None]
    y1_2d_arr = y1[:, None]
    x0_2d_arr = x0[None, :]
    x1_2d_arr = x1[None, :]

    # Four-corner dot product — distance vector needs adjustment
    # Upper left (y0, x0): dist = (dy, dx)
    n00 = grad_x[y0_2d_arr, x0_2d_arr] * dx_2d + grad_y[y0_2d_arr, x0_2d_arr] * dy_2d
    # Upper right (y0, x1): dist = (dy, dx-1)
    n01 = grad_x[y0_2d_arr, x1_2d_arr] * (dx_2d - 1) + grad_y[y0_2d_arr, x1_2d_arr] * dy_2d
    # Lower left (y1, x0): dist = (dy-1, dx)
    n10 = grad_x[y1_2d_arr, x0_2d_arr] * dx_2d + grad_y[y1_2d_arr, x0_2d_arr] * (dy_2d - 1)
    # Lower right (y1, x1): dist = (dy-1, dx-1)
    n11 = grad_x[y1_2d_arr, x1_2d_arr] * (dx_2d - 1) + grad_y[y1_2d_arr, x1_2d_arr] * (dy_2d - 1)

    # bilinear interpolation
    fx_2d = fx[None, :]  # (1, w)
    fy_2d = fy[:, None]  # (h, 1)

    x_interp_0 = _lerp(n00, n01, fx_2d)
    x_interp_1 = _lerp(n10, n11, fx_2d)
    result = _lerp(x_interp_0, x_interp_1, fy_2d)

    return result
