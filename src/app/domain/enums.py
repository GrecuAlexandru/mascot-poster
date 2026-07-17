from enum import Enum


class Focus(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    NEUTRAL = "neutral"


class MascotAnchor(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class SfxKind(str, Enum):
    NONE = "none"
    WHOOSH = "whoosh"
    POSE_POP = "pose_pop"
    FOCUS_TICK = "focus_tick"
    CTA_STING = "cta_sting"


class VisualEventKind(str, Enum):
    REVEAL_LEFT = "reveal_left"
    REVEAL_RIGHT = "reveal_right"
    SHOW_BOTH = "show_both"


class MemoryDeviceKind(str, Enum):
    ANALOGY = "analogy"
    SURPRISING_CORRECTION = "surprising_correction"
    HUMOROUS_CONTRAST = "humorous_contrast"
    REPEATABLE_SENTENCE = "repeatable_sentence"


class ImageMotion(str, Enum):
    NONE = "none"
    SLOW_ZOOM_IN = "slow_zoom_in"
    SLOW_ZOOM_OUT = "slow_zoom_out"
    SLOW_PAN_LEFT = "slow_pan_left"
    SLOW_PAN_RIGHT = "slow_pan_right"
    PULSE = "pulse"


class Transition(str, Enum):
    CUT = "cut"
    QUICK_FADE = "quick_fade"
    CROSSFADE = "crossfade"
    SLIDE = "slide"
    FADE = "fade"


class MascotPose(str, Enum):
    NEUTRAL = "neutral"
    INTRO_HANDS_UP = "intro_hands_up"
    PRESENT_BOTH = "present_both"
    POINT_LEFT = "point_left"
    POINT_RIGHT = "point_right"
    POINT_UP = "point_up"
    POINT_DOWN = "point_down"
    POINT_UP_LEFT = "point_up_left"
    POINT_UP_RIGHT = "point_up_right"
    TWO_FINGERS_UP = "two_fingers_up"
    IDEA = "idea"
    THINKING = "thinking"
    SURPRISED = "surprised"
    EXPLAINING = "explaining"
    COMPARE_LEFT_RIGHT = "compare_left_right"
    THUMBS_UP = "thumbs_up"
    WARNING = "warning"
    SHRUG = "shrug"
    CELEBRATE = "celebrate"
    OUTRO_WAVE = "outro_wave"
    MAGNIFYING_GLASS = "magnifying_glass"
    PHONE_IN_HAND = "phone_in_hand"
    ARMS_CROSSED = "arms_crossed"
    READING_NOTE = "reading_note"
