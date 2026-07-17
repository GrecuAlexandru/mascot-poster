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


_SCRIPT_SYSTEM_PREAMBLE = (
    "You are the narration writer for a Romanian short-form comparison channel (TikTok, YouTube "
    "Shorts, Instagram Reels). Each episode follows one fixed template: two product photos sit side "
    "by side at the top of a vertical frame, a friendly explorer mascot named Pufaila stands at the "
    "bottom and points up at each item in turn, karaoke captions flash the key words, and you answer "
    "one question in about twenty to thirty seconds: what is the real difference between the two "
    "items. You return the narration as STRUCTURED JSON: a list of short spoken 'beats', each with a "
    "stable id and an explicit permitted pause, plus a social caption, hashtags, and a list of "
    "factual claims. Every beat is read aloud by a text-to-speech engine, so it must be plain, fully "
    "speakable text, never an abbreviation, a symbol, or anything you cannot pronounce out loud. "
    "Follow the humanizer rules below so the narration sounds like a sharp, friendly person "
    "explaining something to a friend, never like an encyclopedia or an advertisement.\n\n"
)


_SCRIPT_STRUCTURE_GUIDE = """

STRUCTURA UNUI EPISOD (arcul beat-urilor)
1. HOOK: exact întrebarea de deschidere «Avem X și avem Y. Dar care e diferența?». O spui o
   singură dată, apoi treci direct la explicație.
2. BLOCUL STÂNGA: prezinți una sau două caracteristici concrete ale obiectului din stânga (din ce
   e făcut, de unde vine, cum se comportă), luate strict din fapte.
3. BLOCUL DREAPTA: prezinți exact același număr de caracteristici pentru obiectul din dreapta, ca
   să existe simetrie pe ecran.
4. VERDICT: o singură propoziție scurtă care începe cu «Pe scurt,» și rezumă contrastul, fără
   informații noi.
5. CLOSING: semnătura personajului, «Vă pupă Pufăilă!».
Fiindcă subtitrările karaoke scot în evidență cuvintele cheie, ține beat-urile scurte și
punctează diferența clar, cuvânt cu cuvânt.

EXEMPLU COMPLET (în română, cu diacritice corecte; dacă scrii în altă limbă, păstrează structura
și ritmul, nu limba; lungimile sunt orientative, iar bugetul de cuvinte cerut mai jos are
prioritate; NU refolosi acest subiect sau aceste fapte):
{
  "title": "Unt vs margarină",
  "left_item": "Unt",
  "right_item": "Margarină",
  "hook": "Avem unt și avem margarină. Dar care e diferența?",
  "beats": [
    {"id": "hook", "text": "Avem unt și avem margarină. Dar care e diferența?", "pause_after_ms": 500, "claim_ids": []},
    {"id": "left_origine", "text": "Untul se face din smântână bătută, pur din lapte.", "pause_after_ms": 300, "claim_ids": ["claim_1"]},
    {"id": "left_gust", "text": "Are gust plin și se rumenește frumos la prăjit.", "pause_after_ms": 500, "claim_ids": ["claim_2"]},
    {"id": "right_origine", "text": "Margarina se face din uleiuri de la plante.", "pause_after_ms": 300, "claim_ids": ["claim_3"]},
    {"id": "right_textura", "text": "Rămâne moale direct de la frigider.", "pause_after_ms": 500, "claim_ids": ["claim_4"]},
    {"id": "memory", "text": "Unul vine din lapte, celălalt pornește din plante.", "pause_after_ms": 500, "claim_ids": ["claim_1", "claim_3"]},
    {"id": "verdict", "text": "Pe scurt, unul e din lapte, celălalt din ulei.", "pause_after_ms": 750, "claim_ids": []}
  ],
  "closing": {"id": "closing", "text": "Vă pupă Pufăilă!", "pause_after_ms": 500, "claim_ids": []},
  "caption": "Unt sau margarină? Diferența e în ce sunt făcute, nu doar în preț. Tu cu ce gătești?",
  "hashtags": ["unt", "margarina", "gatit", "diferenta", "pufaila"],
  "memory_device": {"kind": "repeatable_sentence", "line": "Unul vine din lapte, celălalt pornește din plante.", "beat_id": "memory"},
  "claims": [
    {"id": "claim_1", "text": "Untul este făcut din smântână, adică grăsime din lapte.", "supporting_source_ids": ["src_0"], "confidence": 0.95, "risk_level": "low"},
    {"id": "claim_2", "text": "Untul se rumenește la temperaturi de prăjire.", "supporting_source_ids": ["src_1"], "confidence": 0.8, "risk_level": "low"},
    {"id": "claim_3", "text": "Margarina este făcută din uleiuri vegetale.", "supporting_source_ids": ["src_0"], "confidence": 0.95, "risk_level": "low"},
    {"id": "claim_4", "text": "Margarina rămâne moale direct de la frigider.", "supporting_source_ids": ["src_2"], "confidence": 0.85, "risk_level": "low"}
  ]
}
Observă: hook-ul spune întrebarea fixă; două caracteristici pentru stânga și două pentru dreapta
(simetrie); verdictul începe cu «Pe scurt,» și nu aduce nimic nou; closing e doar semnătura;
fiecare afirmație factuală are un claim legat prin claim_ids; tot textul are diacritice corecte și
cuvinte simple («uleiuri de la plante» în beat, nu «uleiuri vegetale rafinate»)."""


_SCRIPT_MEMORY_DEVICE_GUIDE = """

MEMORY DEVICE:
- Return exactly one memory_device object with kind, line, and beat_id.
- kind must be exactly one of: analogy, surprising_correction, humorous_contrast, repeatable_sentence.
- Put the exact 6-20 word line as a complete sentence in one dedicated non-hook, non-closing beat.
- The referenced beat must use claim_ids for every factual idea in the line.
- The line must not add an unsupported fact, measurement, health claim, safety claim, financial claim,
  or causal claim. Prefer a simple non-quantitative comparison grounded only in the supplied facts.
- structural example only: «Frigiderul pune mâncarea pe pauză; congelatorul aproape oprește filmul.»
  Never copy this example, its subject, or its facts into another topic.
"""


_SCRIPT_TTS_RULES = """

REGULI PENTRU TEXT-TO-SPEECH (fiecare beat e citit cu voce tare):
- Scrie totul în cuvinte complete, pronunțabile. Fără abrevieri sau simboluri pentru unități:
  «kilometri pe oră», nu «km/h»; «metri cubi», nu «m3» sau «mc»; «la sută», nu «%»; «grade
  Celsius», nu «grd C»; «lei», nu «RON»; «mililitri», nu «ml»; «grame», nu «g».
- Scrie numerele mici și fracțiile în litere: «trei virgulă cinci», nu «3,5»; «un sfert», nu
  «1/4». Numerele mari rotunjește-le natural în vorbire: «aproape o mie», «de trei ori mai mult».
- Înlocuiește simbolurile cu vorbire: «și» nu «&»; «plus» nu «+»; «sau» ori «pe» în loc de «/».
- Fără acronime nepronunțabile, paranteze, ghilimele, bare oblice, emoji sau notație tehnică în
  beat-uri; reformulează în vorbire naturală. (Emoji sunt permise DOAR în caption, nu în beat-uri.)
- Dacă un nume propriu sau o marcă e greu de pronunțat, scrie-l fonetic sau evită-l."""


_SCRIPT_CLAIMS_CAPTION_GUIDE = """

CLAIM-URI, CAPTION ȘI HASHTAG-URI:
- claims: listează fiecare afirmație factuală verificabilă pe care o face narațiunea, câte una per
  claim, cu id claim_1, claim_2 și așa mai departe. Textul claim-ului e afirmația clară (poate fi
  o reformulare curată a beat-ului). Pune în supporting_source_ids sursele din fapte care o
  susțin, dă un confidence între zero și unu și un risk_level: «low» implicit, «medium» dacă
  atinge sănătate, bani sau siguranță, «high» doar dacă e ușor de spus ceva dăunător. Nu afirma
  nimic care nu e susținut de faptele de mai jos, fiindcă un verificator compară claim-urile cu
  faptele. Leagă fiecare beat de claim-urile lui prin claim_ids.
- caption: o descriere scurtă în limba episodului, una sau două propoziții plus o întrebare care
  stârnește comentarii, cu câteva emoji potrivite. Ton prietenos și onest, fără clickbait.
- hashtags: patru până la șase etichete scurte, cu litere mici, fără diez și fără spații."""


_SCRIPT_LANGUAGE_RULES = """

DIACRITICE ȘI ORTOGRAFIE (foarte important):
Scrie o română perfectă, cu TOATE diacriticele corecte (ă, â, î, ș, ț) și fără nicio greșeală de
ortografie. Motorul text-to-speech pronunță greșit cuvintele scrise fără diacritice sau greșit, așa
că fiecare cuvânt trebuie scris corect și complet. Verifică fiecare cuvânt înainte de a-l scrie.
Exemple de greșeli exacte de evitat:
- scrie «tavă», nu «tava»; «la tavă», nu «la tava».
- scrie «groasă», nu «grosă»; «gros», la feminin, se scrie «groasă».
- scrie «coajă», nu «coaja» când e nearticulat; «brânză», nu «branza»; «pâine», nu «paine».
- scrie «făcut», nu «facut»; «rămâne», nu «ramane»; «și», nu «si»; «diferență», nu «diferenta».

LIMBAJ SIMPLU:
Folosește cuvinte simple, de zi cu zi, pe care le înțelege oricine, chiar și un copil de zece ani.
Fraze scurte, o idee pe rând. Fără termeni tehnici, cuvinte pretențioase sau ton profesionist. Dacă
un cuvânt e complicat, înlocuiește-l cu unul mai simplu sau explică-l în două cuvinte simple (de
exemplu spune «uleiuri din plante» în loc de «uleiuri vegetale rafinate», «se strică mai greu» în
loc de «are o perioadă de conservare extinsă»). Nu simplifica ideea în sine, doar limbajul: rămâi
exact, dar ușor de urmărit de oricine."""


@lru_cache(maxsize=1)
def _humanizer_guidance() -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / "humanizer.md"
    return path.read_text(encoding="utf-8")


class ReferenceScriptService:
    def __init__(self, llm: object, proofreader: object | None = None):
        self.llm = llm
        self.proofreader = proofreader

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
        system = _SCRIPT_SYSTEM_PREAMBLE + _humanizer_guidance()
        user = (
            f"Scrie în {language_name}. Topic: {topic.title}. "
            f"Stânga: {left}. Dreapta: {right}. "
            f"Țintă orientativă: {target_duration_seconds} secunde; this is an approximate pacing target, "
            "not a strict duration gate. "
            f"{dialogue_style}"
            + _SCRIPT_STRUCTURE_GUIDE
            + "\n\nREGULI DE STRUCTURĂ ȘI RITM:\n"
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
            + _SCRIPT_TTS_RULES
            + (_SCRIPT_LANGUAGE_RULES if language == "ro" else "")
            + _SCRIPT_MEMORY_DEVICE_GUIDE
            + _SCRIPT_CLAIMS_CAPTION_GUIDE
            + "\n\nNu inventa fapte în afara listei. "
            "Dacă reparațiile cer eliminarea unei afirmații, elimină complet beat-ul și claim-ul "
            "corespunzător; dacă cer atenuarea, folosește exact formularea mai prudentă cerută, "
            "fără a adăuga fapte sau surse noi."
            "\n\nFAPTE DISPONIBILE (folosește doar acestea):\n"
            + facts
            + "\n\nREPARAȚII CERUTE:\n"
            + chr(10).join(repair_notes or ["niciuna"])
        )
        result = await self.llm.complete_structured(
            system,
            user,
            ReferenceScriptPackage,
            schema_name="reference_script",
            temperature=0.35,
            max_tokens=5000,
        )
        script = self._enforce_bookends(
            result,
            topic,
            opening_line,
            signoff_line,
            summary_prefix,
        )
        if self.proofreader is not None and language == "ro":
            script = await self.proofreader.correct_script(script)
        return script

    @staticmethod
    def _enforce_bookends(
        result: ReferenceScriptPackage,
        topic: TopicSpec,
        opening_line: str,
        signoff_line: str,
        summary_prefix: str,
    ) -> ReferenceScriptPackage:
        beats = list(result.beats)
        if beats and beats[0].text.strip().casefold() == opening_line.casefold():
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
                pause_after_ms=750,
            ))
        elif len(beats) > 1:
            last = beats[-1]
            beats[-1] = last.model_copy(update={
                "text": ReferenceScriptService._summary_text(last.text, summary_prefix),
                "pause_after_ms": 750,
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
