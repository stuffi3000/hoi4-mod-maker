"""Preview function — combine the current map into an "in-game look and feel" screen and display it on the canvas.

Compositing pipeline: domain/preview/compositor.py (game texture + height lighting + climate tone
+ ocean depth + river). Game textures come from the HOI4 installation directory of the user's machine
(services/game_assets.py), if it cannot be found, it will be downgraded to the continent view and a prompt will be displayed in the sidebar.

The whole image synthesis takes about 2~5 seconds, so the results are cached and refreshed manually, and the editing is not followed in real time."""

from features.base import BaseFeature, FeatureContext


class PreviewFeature(BaseFeature):
    id = "map.preview"
    display_name = "Preview"
    category = "map"

    def build_page(self, ctx: FeatureContext):
        from features.map.preview.page import PreviewPage
        return PreviewPage()

    def build_renderer(self, ctx: FeatureContext):
        from features.map.preview import renderer
        return renderer
