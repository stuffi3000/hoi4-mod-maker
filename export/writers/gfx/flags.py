"""Flag TGA generated."""
import os


def write_country_flags(tags, output_dir, country_mgr=None):
    """Generate flag files for each country.
    HOI4 requires gfx/flags/TAG.tga to exist, otherwise the UI will report an error (which may affect interaction).
    Format: 82x52 TGA, 24-bit BGR bottom-up."""
    import struct
    flag_dir = os.path.join(output_dir, "gfx", "flags")
    os.makedirs(flag_dir, exist_ok=True)
    # Medium and small flags are also required
    med_dir = os.path.join(flag_dir, "medium")
    small_dir = os.path.join(flag_dir, "small")
    os.makedirs(med_dir, exist_ok=True)
    os.makedirs(small_dir, exist_ok=True)

    # A set of default colors, hashed by TAG
    default_colors = [
        (200, 80, 80), (80, 80, 200), (80, 200, 80), (200, 200, 80),
        (200, 80, 200), (80, 200, 200), (150, 100, 50), (100, 150, 200),
    ]

    def make_tga(path, w, h, rgb):
        r, g, b = rgb
        # TGA file header (18 bytes) - 32bpp BGRA format (HOI4 recommended, faster reading)
        header = struct.pack(
            "<BBBHHBHHHHBB",
            0,      # ID length
            0,      # Color map type
            2,      # Image type (uncompressed true color)
            0, 0, 0,    # Color map spec
            0, 0,       # X, Y origin
            w, h,       # Width, Height
            32,         # Pixel depth (32bpp)
            8,          # Image descriptor: 8 = 8bit alpha + bottom-up
        )
        # Pixel data: BGRA order, A=255 (opaque)
        pixel = bytes([b, g, r, 255]) * (w * h)
        with open(path, "wb") as f:
            f.write(header)
            f.write(pixel)

    ideologies = ["neutrality", "democratic", "fascism", "communism"]

    for i, tag in enumerate(tags):
        # Get country colors
        if country_mgr and tag in country_mgr.countries:
            rgb = country_mgr.countries[tag].color
        else:
            rgb = default_colors[i % len(default_colors)]

        # Main flag 82x52
        make_tga(os.path.join(flag_dir, f"{tag}.tga"), 82, 52, rgb)
        # Ideology variant (HOI4 requires TAG_ideology.tga)
        for ideo in ideologies:
            make_tga(os.path.join(flag_dir, f"{tag}_{ideo}.tga"), 82, 52, rgb)
        # medium flag 41x26
        make_tga(os.path.join(med_dir, f"{tag}.tga"), 41, 26, rgb)
        for ideo in ideologies:
            make_tga(os.path.join(med_dir, f"{tag}_{ideo}.tga"), 41, 26, rgb)
        # small flag 10x7
        make_tga(os.path.join(small_dir, f"{tag}.tga"), 10, 7, rgb)
        for ideo in ideologies:
            make_tga(os.path.join(small_dir, f"{tag}_{ideo}.tga"), 10, 7, rgb)

