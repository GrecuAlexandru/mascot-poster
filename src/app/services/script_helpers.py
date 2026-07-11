from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.domain.models import ScenePlan, SceneSpec, ScriptPackage
from app.domain.enums import Focus, MascotPose


def script_to_render_spec(
    script: ScriptPackage,
    left_image: Path,
    right_image: Path,
    audio: Path,
    template: str = "comparison_v1",
    mascot_set: str = "default",
    narration_text: Optional[str] = None,
) -> "RenderSpec":
    from app.domain.models import RenderSpec

    scenes: list[SceneSpec] = []
    cumulative = 0.0
    for plan in script.scenes:
        start = cumulative
        end = cumulative + plan.duration_hint_seconds
        cumulative = end

        phrase = plan.on_screen_phrases[0] if plan.on_screen_phrases else ""
        scenes.append(SceneSpec(
            start=round(start, 3),
            end=round(end, 3),
            pose=plan.mascot_pose,
            phrase=phrase,
            focus=plan.focus,
            image_motion=plan.image_motion,
            transition=plan.transition,
        ))

    return RenderSpec(
        title=script.title,
        left_label=script.title.split(" vs ")[0] if " vs " in script.title else "Left",
        right_label=script.title.split(" vs ")[1] if " vs " in script.title else "Right",
        left_image=left_image,
        right_image=right_image,
        audio=audio,
        scenes=scenes,
        template=template,
        mascot_set=mascot_set,
        narration_text=narration_text or script.narration_text,
    )


def create_sample_script() -> ScriptPackage:
    narration = (
        "Vanilla sugar and vanillin sugar. They look almost identical, "
        "but they are not the same thing. "
        "Vanilla sugar is made with real vanilla beans, "
        "which contain natural vanillin extracted from the orchid pod. "
        "Vanillin sugar uses artificial vanillin, "
        "a synthetic compound that mimics the flavor. "
        "The difference matters. "
        "Natural vanilla has over two hundred flavor compounds, "
        "while artificial vanillin only provides one. "
        "That is why vanilla sugar tastes richer and more complex. "
        "Vanillin sugar is cheaper, but simpler. "
        "So check the labels carefully. "
        "If it says vanilla, you get the real thing. "
        "If it says vanillin, it is artificial. "
        "They may look similar, but choose wisely."
    )

    sentences = [
        "Vanilla sugar and vanillin sugar.",
        "They look almost identical, but they are not the same thing.",
        "Vanilla sugar is made with real vanilla beans, which contain natural vanillin extracted from the orchid pod.",
        "Vanillin sugar uses artificial vanillin, a synthetic compound that mimics the flavor.",
        "The difference matters.",
        "Natural vanilla has over two hundred flavor compounds, while artificial vanillin only provides one.",
        "That is why vanilla sugar tastes richer and more complex.",
        "Vanillin sugar is cheaper, but simpler.",
        "So check the labels carefully.",
        "If it says vanilla, you get the real thing.",
        "If it says vanillin, it is artificial.",
        "They may look similar, but choose wisely.",
    ]

    durations = [5.0, 6.0, 8.0, 7.0, 3.0, 6.0, 5.0, 5.0, 3.0, 4.0, 4.0, 4.0]

    poses = [
        MascotPose.INTRO_HANDS_UP,
        MascotPose.COMPARE_LEFT_RIGHT,
        MascotPose.POINT_LEFT,
        MascotPose.POINT_RIGHT,
        MascotPose.SURPRISED,
        MascotPose.THINKING,
        MascotPose.POINT_LEFT,
        MascotPose.POINT_RIGHT,
        MascotPose.WARNING,
        MascotPose.POINT_LEFT,
        MascotPose.POINT_RIGHT,
        MascotPose.THUMBS_UP,
    ]

    focuses = [
        Focus.BOTH,
        Focus.BOTH,
        Focus.LEFT,
        Focus.RIGHT,
        Focus.BOTH,
        Focus.BOTH,
        Focus.LEFT,
        Focus.RIGHT,
        Focus.BOTH,
        Focus.LEFT,
        Focus.RIGHT,
        Focus.BOTH,
    ]

    phrases = [
        "THEY LOOK SIMILAR",
        "NOT THE SAME",
        "NATURAL VANILLA",
        "ARTIFICIAL VANILLIN",
        "KEY DIFFERENCE",
        "200 COMPOUNDS",
        "RICHER TASTE",
        "CHEAPER OPTION",
        "CHECK LABELS",
        "REAL VANILLA",
        "ARTIFICIAL",
        "CHOOSE WISELY",
    ]

    from app.domain.enums import ImageMotion, Transition

    scenes = []
    for i in range(len(sentences)):
        scenes.append(ScenePlan(
            index=i,
            narration=sentences[i],
            duration_hint_seconds=durations[i],
            mascot_pose=poses[i],
            focus=focuses[i],
            on_screen_phrases=[phrases[i]],
            transition=Transition.FADE if i == 0 or i == len(sentences) - 1 else Transition.QUICK_FADE,
            image_motion=ImageMotion.SLOW_ZOOM_IN if i % 2 == 0 else ImageMotion.SLOW_PAN_RIGHT,
            emphasis=[],
        ))

    return ScriptPackage(
        title="Vanilla sugar vs vanillin sugar",
        hook="They look almost identical, but they are not the same thing.",
        narration_text=narration,
        caption="Did you know vanilla sugar and vanillin sugar are completely different? Check the labels next time you shop!",
        hashtags=["vanilla", "vanillin", "foodfacts", "comparison", "didyouknow"],
        claims=[
            {"id": "claim_1", "text": "Vanilla sugar contains natural vanillin from orchid pods", "confidence": 0.95, "risk_level": "low"},
            {"id": "claim_2", "text": "Vanillin sugar uses artificial vanillin", "confidence": 0.9, "risk_level": "low"},
            {"id": "claim_3", "text": "Natural vanilla has over 200 flavor compounds", "confidence": 0.85, "risk_level": "low"},
        ],
        scenes=scenes,
        estimated_duration_seconds=60.0,
    )
