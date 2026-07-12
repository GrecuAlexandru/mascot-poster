from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.domain.models import ClosingBeat, NarrationBeat, ReferenceScriptPackage, ResearchPackage, TopicSpec

MASCOT_NAME = "Pufăilă"
ROMANIAN_DIALOGUE_STYLE_EXAMPLE = (
    "Avem zahăr vanilat și avem zahăr vanilinat. Dar care e diferența?\n"
    "Zahărul vanilat e făcut din vanilie naturală, extract sau păstăi adevărate. "
    "E mai scump, dar aroma e complexă, cu note de miere și caramel.\n"
    "Zahărul vanilinat, în schimb, conține vanilină, aromă sintetică. Costă de patru "
    "ori mai puțin, dar aroma e mai simplă, mai puternică la început și dispare mai "
    "repede la copt.\n"
    "Pe scurt, unul e originalul, celălalt e remake-ul.\n"
    "Vă pupă Pufăilă!"
)


@lru_cache(maxsize=1)
def _humanizer_guidance() -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / "humanizer.md"
    return path.read_text(encoding="utf-8")


class ReferenceScriptService:
    def __init__(self, llm: object):
        self.llm = llm

    async def generate(
        self,
        topic: TopicSpec,
        research: ResearchPackage,
        target_duration_seconds: int,
        language: str,
        repair_notes: list[str] | None = None,
    ) -> ReferenceScriptPackage:
        facts = "\n".join(f"- {fact.text}" for fact in research.facts) or "- Fără fapte suplimentare"
        language_name = "română" if language == "ro" else "English"
        word_budget = target_duration_seconds * 2
        left = topic.comparison_left
        right = topic.comparison_right
        if language == "en":
            opening_line = f"We have {left} and we have {right}. But what's the difference?"
            signoff_line = f"Hugs from {MASCOT_NAME}!"
            summary_prefix = "In short,"
        else:
            opening_line = f"Avem {left} și avem {right}. Dar care e diferența?"
            signoff_line = f"Vă pupă {MASCOT_NAME}!"
            summary_prefix = "Pe scurt,"
        if language == "ro":
            dialogue_style = (
                "Tonul trebuie să fie modern, relaxat și direct, ca un om care îi explică unui "
                "prieten. Poți folosi ironie ușoară, comparații jucăușe și cuvinte moderne când "
                "vin natural. Nu suna educațional, academic, corporatist sau excesiv de profesionist. "
                "Nu forța slang-ul, glumele ori poantele și nu sacrifica exactitatea pentru umor. "
                "Exemplul următor este numai pentru ritm, structură și ton; nu reutiliza faptele, "
                "valorile sau afirmațiile lui în noul dialog:\n"
                f"{ROMANIAN_DIALOGUE_STYLE_EXAMPLE}\n"
            )
        else:
            dialogue_style = (
                "Use a modern, relaxed, direct voice, like someone explaining the difference to a "
                "friend. Light irony, playful comparisons, and contemporary wording are welcome when "
                "they feel natural. Do not sound academic, corporate, or overly professional. Do not "
                "force slang or jokes, and never trade factual accuracy for humor.\n"
            )
        system = (
            "You write factual short-form comparison narration as structured JSON. "
            "Return short spoken beats with explicit permitted pauses. "
            "The narration is read aloud by a text-to-speech engine, so every beat "
            "must be plain speakable text. Follow the humanizer rules so the narration "
            "sounds like a real person, never like an article or an ad.\n\n"
            f"{_humanizer_guidance()}"
        )
        user = (
            f"Scrie în {language_name}. Topic: {topic.title}. "
            f"Stânga: {left}. Dreapta: {right}. "
            f"Țintă: {target_duration_seconds} secunde. "
            f"{dialogue_style}"
            "Folosește 4-7 beat-uri de explicație, text vorbit natural, fiecare cu un id stabil, "
            "iar pause_after_ms trebuie să fie una dintre 0, 150, 300, 500, 750, 1000. "
            "Preferă pauze de 300-500 ms între ideile corpului și folosește 150 ms doar între "
            "fraze scurte care trebuie să curgă împreună. "
            f"PRIMUL beat trebuie să fie exact această deschidere, cuvânt cu cuvânt: "
            f"«{opening_line}» (folosește pause_after_ms 500). "
            "Beat-urile următoare explică diferența reală folosind faptele de mai jos. "
            "Prezintă același număr de caracteristici concrete pentru stânga și dreapta; "
            "nu descrie mai multe caracteristici pentru un obiect decât pentru celălalt. "
            f"ULTIMUL beat de explicație înainte de closing trebuie să fie o singură concluzie scurtă "
            f"care începe exact cu «{summary_prefix}» și are 4-12 cuvinte după prefix. "
            "Nu repeta explicațiile și nu adăuga detalii noi în această concluzie. "
            "Adaugă separat closing cu id exact closing, iar textul lui trebuie să fie doar semnătura cerută. "
            f"Textul closing trebuie să fie exact «{signoff_line}», ca semnătură a "
            f"personajului {MASCOT_NAME}. Pune pause_after_ms 500 la closing. "
            f"Textul vorbit total trebuie să aibă cel mult {word_budget} cuvinte. "
            "Textul este citit de un motor text-to-speech, deci scrie totul în cuvinte "
            "complete, pronunțabile: fără abrevieri sau simboluri pentru unități "
            "(scrie «kilometri pe oră», nu «km/h»; «metri cubi», nu «m³» sau «mc»; "
            "«la sută», nu «%»; «grade Celsius», nu «°C»; «lei», nu «RON»). "
            "Scrie numerele mici și fracțiile în litere («trei virgulă cinci», nu «3,5»). "
            "Evită acronimele nepronunțabile, parantezele, ghilimelele, barele oblice "
            "și orice notație tehnică — reformulează în vorbire naturală. "
            "Nu inventa fapte în afara listei. "
            "Dacă reparațiile cer eliminarea unei afirmații, elimină complet beat-ul și claim-ul "
            "corespunzător; dacă cer atenuarea, folosește exact formularea mai prudentă cerută, "
            "fără a adăuga fapte sau surse noi.\nFapte:\n"
            f"{facts}\nReparații cerute:\n{chr(10).join(repair_notes or ['niciuna'])}"
        )
        result = await self.llm.complete_structured(
            system,
            user,
            ReferenceScriptPackage,
            schema_name="reference_script",
            temperature=0.35,
            max_tokens=2800,
        )
        return self._enforce_bookends(
            result,
            topic,
            opening_line,
            signoff_line,
            summary_prefix,
        )

    @staticmethod
    def _enforce_bookends(
        result: ReferenceScriptPackage,
        topic: TopicSpec,
        opening_line: str,
        signoff_line: str,
        summary_prefix: str,
    ) -> ReferenceScriptPackage:
        beats = list(result.beats)
        if beats and beats[0].text.strip() == opening_line:
            beats[0] = beats[0].model_copy(update={
                "id": "hook",
                "text": opening_line,
                "pause_after_ms": 500,
            })
        else:
            beats.insert(0, NarrationBeat(
                id="hook",
                text=opening_line,
                pause_after_ms=500,
            ))
        conclusion = ReferenceScriptService._conclusion_before_signoff(
            result.closing.text,
            signoff_line,
        )
        if conclusion:
            existing_ids = {beat.id for beat in beats}
            conclusion_id = "verdict"
            index = 2
            while conclusion_id in existing_ids:
                conclusion_id = f"verdict_{index}"
                index += 1
            beats.append(NarrationBeat(
                id=conclusion_id,
                text=ReferenceScriptService._summary_text(conclusion, summary_prefix),
                pause_after_ms=1000,
            ))
        elif len(beats) > 1:
            last = beats[-1]
            beats[-1] = last.model_copy(update={
                "text": ReferenceScriptService._summary_text(last.text, summary_prefix),
                "pause_after_ms": 1000,
            })
        return result.model_copy(update={
            "title": topic.title,
            "left_item": topic.comparison_left,
            "right_item": topic.comparison_right,
            "hook": opening_line,
            "beats": beats,
            "closing": ClosingBeat(
                id="closing",
                text=signoff_line,
                pause_after_ms=500,
            ),
        })

    @staticmethod
    def _conclusion_before_signoff(closing_text: str, signoff_line: str) -> str:
        closing = " ".join(closing_text.split())
        if closing.casefold().endswith(signoff_line.casefold()):
            closing = closing[:len(closing) - len(signoff_line)].rstrip()
        return closing.strip()

    @staticmethod
    def _summary_text(text: str, summary_prefix: str) -> str:
        compact = " ".join(text.split())
        if compact.casefold().startswith(summary_prefix.casefold()):
            return compact
        return f"{summary_prefix} {compact}"
