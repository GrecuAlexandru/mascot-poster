class RenderError(Exception):
    pass


class TemplateNotFoundError(RenderError):
    pass


class MascotAssetError(RenderError):
    pass


class FFmpegError(RenderError):
    pass


class AssetValidationError(RenderError):
    pass
