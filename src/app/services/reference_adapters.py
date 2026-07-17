from __future__ import annotations

import asyncio
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.domain.models import (
    ReferenceScriptPackage,
    ResearchFact,
    ResearchPackage,
    TopicCandidate,
    TopicSpec,
    VerificationResult,
)
from app.services.research_service import ResearchService
from app.services.topic_selection_service import TopicSelectionService


_TOPIC_SYSTEM_PROMPT = (
    "You are the head idea writer for a Romanian short-form comparison channel that runs on "
    "TikTok, YouTube Shorts, and Instagram Reels. Every episode is built from the SAME rigid "
    "template: two real physical objects sit side by side at the top of a vertical 1080x1920 "
    "frame, a friendly explorer mascot named Pufaila stands at the bottom and points up at each "
    "one in turn, karaoke captions flash the key words, and a narrator answers a single question "
    "in about 20 to 30 seconds: 'care e diferenta?'. There is no b-roll, no diagram, no screen "
    "recording, no chart. The entire video is two photographs and a talking mascot. Your only job "
    "in this step is to invent a candidate pool that this exact template can actually shoot and "
    "explain. Return structured JSON only, no prose around it."
)

_TOPIC_INSTRUCTIONS = """Your task: invent exactly six fresh comparison candidates for the next episode.
The application scores and ranks them, so make them genuinely different alternatives instead of
putting one favorite first.

PRIMARY EDITORIAL RULE: CONFUSION TENSION
A strong topic begins with a mistake, disagreement, or misconception people already have. Prefer
names used interchangeably, mistaken identities, Romanian regional or household disagreements,
familiar myths, and distinctions viewers would send to a friend to settle an argument. Reject
obvious-category pairs whose answer nearly everyone already understands. Two objects merely being
different is not enough.

WHY THIS TEMPLATE IS SO PICKY
Because the whole video is just two isolated product photos plus a narrator, a topic
only works when BOTH of these are true at the same time:
  (a) a viewer can tell the two items apart INSTANTLY from a still photo, with no text,
      no label, and no logo to read, and
  (b) there is a real, checkable, factual difference between them that is worth about
      twenty seconds of explanation.
If either half fails, the episode literally cannot be produced, so do not propose it.

HARD RULES
1. Exactly TWO items. Both must be concrete physical things: foods, drinks, ingredients,
   materials, plants, animals, tools, devices, household objects, vehicles, or buildings.
2. Both items must survive as a clean, isolated product cutout that a stock-photo search
   or an image model can render on a plain background with NO readable text. If telling the
   item apart depends on reading a label, a printed number, a brand name, or interface copy,
   the topic is banned.
3. The two items must look OBVIOUSLY different in a photograph: different shape, colour,
   form, size, or texture. If the only real difference is a faint shade of the same powder,
   liquid, paste, oil, or pill, reject it. The camera cannot sell an invisible difference.
4. There must be a genuine factual contrast (ingredient, origin, production process, use,
   nutrition, durability, energy use, or cost), not a matter of taste or personal opinion.
5. The 'left' and 'right' fields are SHORT, plain item names, at most four words each, with
   no brand name and no explanation. Every qualifier, number, and nuance belongs in 'angle'.
6. The pair must be broadly familiar to a Romanian audience: things people here actually buy,
   eat, cook with, or own. Prefer everyday over exotic.
7. Do not generate abstract concepts, writing styles, SEO tactics, personality types, habits, or
   processes. Nothing that would need readable paragraphs, URLs, warning labels, charts, diagrams,
   brand logos, or interface copy to recognize belongs on this channel.
8. No medical diagnosis or treatment advice, no legal advice, nothing dangerous to imitate.
9. Strongly prefer the 'stai, chiar asa?' reaction: two things people assume are the same,
   or use interchangeably, but that differ in a way most viewers were never taught.
10. Vary the domain away from the recent history below; do not cluster in one category.

GOOD TOPICS (illustration only, DO NOT reuse these exact pairs)
- Unt / Margarina -> one is churned cream, the other refined vegetable oil; a hard block
  versus a soft tub reads on camera in half a second. Domain: food fats.
- Miere cristalizata / Miere lichida -> the very same honey in two visibly different states;
  most people wrongly think the crystallized jar has spoiled. Domain: pantry myth.
- Bec cu LED / Bec incandescent -> a diode board versus a glowing coiled filament look
  nothing alike, and the energy gap is enormous. Domain: household.
- Ou de gaina / Ou de prepelita -> the size gap and the speckled shell are the whole shot;
  nutrition per gram genuinely differs. Domain: groceries.
- Ceai verde / Ceai negru -> same plant, different oxidation, clearly different leaf and
  brew colour. Domain: drinks.
- Sampon solid / Sampon lichid -> a bar versus a bottle; water content, packaging waste, and
  lifespan all differ. Domain: cosmetics.
- Rosii cherry / Rosii normale -> the size difference fills the frame, and sugar content and
  cooking behaviour differ. Domain: produce.

BAD TOPICS (and the exact reason each is rejected here)
- 'SEO on-page vs off-page' -> abstract; there is nothing physical to photograph.
- 'Introvertit vs extrovertit' -> a behaviour, not an object.
- 'Apa plata vs apa minerala' -> the two bottles look identical; the whole difference lives
  on the label, and reading text is banned.
- 'Lapte 1.5% vs lapte 3.5%' -> the cartons are the same; the only cue is a printed number.
- 'Zahar pudra vs zahar tos' -> two near-identical white substances the camera cannot reliably
  tell apart.
- 'iOS vs Android' -> recognizing them needs logos and interface copy; out of scope for this
  bare two-photo format.

FIELD-BY-FIELD GUIDE
- title: a short, punchy Romanian line naming the duel, e.g. 'Unt vs margarina'. Keep it plain
  and honest; no clickbait, no 'nu o sa-ti vina sa crezi'.
- left / right: the two item names in Romanian, at most four words, no brand, no qualifier.
- angle: one to three Romanian sentences naming the concrete difference the episode will explain
  and why a viewer should care. ALL the substance lives here.
- why_it_might_work: one Romanian sentence on the scroll-stopping hook (the misconception, the
  surprise, or the everyday stakes).
- risk_level: 'low' for harmless everyday items; 'medium' when a claim touches health, money, or
  safety and must be worded carefully; 'high' only when it is easy to state something harmful.
  Prefer low and medium; avoid high.
- selection_signals: all seven signals below. Each contains an integer score from zero through five
  and a concise, pair-specific reason. Zero means absent, three means meaningful, and five means
  unusually strong. Generic praise such as 'this is engaging' is invalid.
  - common_confusion: how often people confuse the names, identities, meanings, or uses.
  - everyday_familiarity: how recognizable and relevant the pair is in ordinary Romanian life.
  - cultural_debate: strength of regional, linguistic, household, or cultural disagreement.
  - surprising_payoff: strength of the factual correction or reveal.
  - shareability: likelihood of sending it to someone or using it to settle a disagreement.
  - visual_feasibility: how clearly two still images and short labels establish the comparison.
  - research_risk: difficulty and potential harm of stating the distinction correctly. Higher is worse.

DIACRITICE ȘI LIMBAJ (very important — the output is Romanian):
Write title, left, right, angle, and why_it_might_work in flawless Romanian with correct diacritics
(ă, â, î, ș, ț) and no spelling mistakes. The left and right item names must be the natural, correct
Romanian form of the object. Examples of mistakes to avoid: write 'Pâine la tavă', not 'Pâine la
tava'; 'brânză', not 'branza'; 'pâine', not 'paine'; 'ouă', not 'oua'. Use simple, everyday words
anyone would understand, not technical or fancy terms.

WORKED EXAMPLE (shape and tone only, do not reuse the pair; return six entries, not one)
{
  "topics": [
    {
      "title": "Miere cristalizată vs miere lichidă",
      "left": "Miere cristalizată",
      "right": "Miere lichidă",
      "angle": "Sunt aceeași miere în stări diferite. Cristalizarea este naturală, nu un semn că mierea s-a stricat.",
      "why_it_might_work": "Mulți aruncă borcanul cristalizat crezând că este stricat.",
      "risk_level": "low",
      "selection_signals": {
        "common_confusion": {"score": 5, "reason": "Mulți confundă cristalizarea cu alterarea."},
        "everyday_familiarity": {"score": 5, "reason": "Mierea este prezentă în multe gospodării românești."},
        "cultural_debate": {"score": 3, "reason": "Părerile despre mierea cristalizată diferă între familii."},
        "surprising_payoff": {"score": 5, "reason": "Răspunsul răstoarnă mitul că borcanul s-a stricat."},
        "shareability": {"score": 5, "reason": "Explicația poate opri pe cineva să arunce mierea."},
        "visual_feasibility": {"score": 5, "reason": "Cele două stări se văd clar în borcane alăturate."},
        "research_risk": {"score": 1, "reason": "Procesul este bine documentat și cu risc redus."}
      }
    }
  ]
}

Return one JSON object containing exactly six topics. Every candidate must include all seven
selection signals and must be clearly representable and factually distinct."""


_RESEARCH_SYSTEM_PROMPT = (
    "You are a research analyst for a Romanian short-form comparison channel. You turn a raw list "
    "of web search results into a very small set of tight, trustworthy, TTS-ready factual "
    "contrasts that a scriptwriter will read aloud in about twenty to thirty seconds. You use ONLY "
    "the supplied source results, you never invent facts from general knowledge, and you return "
    "structured JSON only."
)

_RESEARCH_INSTRUCTIONS = """HOW TO SYNTHESIZE THE RESEARCH

You receive a comparison topic and a numbered list of source results (each with an id, a title,
and a URL). Extract the handful of facts that will make the strongest, safest, most watchable
comparison script, obeying every rule below.

WHAT A GOOD FACT LOOKS LIKE
- It states ONE concrete, checkable difference between the two items (ingredient, origin,
  process, nutrition, use, durability, energy, cost, storage, or behaviour).
- It is short and speakable: aim for a single clause a narrator can say in one breath, well
  under 280 characters.
- It is written in clear, natural Romanian, faithful to the source meaning (translate English
  sources, never distort them).
- It is genuinely contrastive. 'Cafeaua conține cofeină' is weak on its own; 'Cafeaua are de
  câteva ori mai multă cofeină decât ceaiul negru la aceeași cantitate' is a real contrast.
- It cites the source id (or ids) it actually came from, one to three of them.
- It is written in flawless Romanian with correct diacritics (ă, â, î, ș, ț) and simple, everyday
  words a scriptwriter can read aloud unchanged.

HARD RULES
1. Use ONLY the listed sources. If nothing in the list supports a claim, do not make the claim.
2. If the sources are thin or contradictory, return FEWER facts and add an unresolved_question
   instead of guessing. Two solid facts beat six shaky ones.
3. Return at most 6 facts. In practice three to five well-chosen facts is ideal for a 20-30s
   script; more than that cannot fit and dilutes the video.
4. Balance the two sides. The script shows the same number of features per item, so try to give
   a comparable count of 'left' facts and 'right' facts; use 'both' for shared context and
   'general' only for framing that fits neither side alone.
5. Prefer facts that are concrete and experiential (something a viewer can picture, taste, feel,
   or measure) over vague marketing language. Drop promotional adjectives entirely.
6. Do NOT return the source objects themselves; the application already stores those. Return only
   facts, unresolved_questions, and safety_notes.
7. Keep unresolved_questions and safety_notes to at most three each. Raise a safety_note whenever
   a fact touches allergens, health limits, medication, children, or anything a viewer could
   misuse.

CONFIDENCE CALIBRATION
- 0.9 to 1.0: stated directly and consistently by a strong, on-topic source.
- 0.7 to 0.85: supported but slightly indirect, approximate, or from a single decent source.
- 0.4 to 0.65: plausible but weakly sourced or partly inferred. Below 0.4, prefer to drop it.

APPLIES_TO
- 'left' -> the fact describes only the left item. 'right' -> only the right item.
- 'both' -> a shared property stated as a contrast point. 'general' -> neutral framing.

WORKED EXAMPLE (topic: Cafea vs Ceai; illustration only; note the correct diacritics)
{
  "facts": [
    {"text": "La aceeași cană, cafeaua are de obicei de câteva ori mai multă cofeină decât ceaiul negru.", "source_ids": ["src_0", "src_2"], "confidence": 0.9, "applies_to": "left"},
    {"text": "Ceaiul negru conține L-teanină, care dă o stare de alertă mai calmă decât cafeaua.", "source_ids": ["src_1"], "confidence": 0.75, "applies_to": "right"},
    {"text": "Ambele băuturi conțin antioxidanți, dar de tipuri diferite: polifenoli în cafea, catechine în ceai.", "source_ids": ["src_2"], "confidence": 0.8, "applies_to": "both"}
  ],
  "unresolved_questions": ["Sursele nu sunt de acord asupra cantității exacte de cofeină dintr-un espresso."],
  "safety_notes": ["Cofeina în exces poate afecta somnul; de evitat formulările care o recomandă medical."]
}

Now read the topic and the sources below and return the JSON summary."""


class ReferenceResearchFact(BaseModel):
    text: str = Field(min_length=1, max_length=280)
    source_ids: list[str] = Field(min_length=1, max_length=3)
    confidence: float = Field(ge=0.0, le=1.0)
    applies_to: Literal["left", "right", "both", "general"] = "general"


class ReferenceResearchSummary(BaseModel):
    facts: list[ReferenceResearchFact] = Field(default_factory=list, max_length=6)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=3)
    safety_notes: list[str] = Field(default_factory=list, max_length=3)


class ReferenceTopicPool(BaseModel):
    topics: list[TopicCandidate] = Field(min_length=1, max_length=6)


class ReferenceTopicGenerator:
    def __init__(
        self,
        llm: object,
        history: Optional[object] = None,
        proofreader: Optional[object] = None,
    ):
        self.llm = llm
        self.history = history
        self.proofreader = proofreader
        self.selector = TopicSelectionService()

    async def generate(self, request) -> TopicSpec:
        if request.topic_override:
            return self._parse_override(request.topic_override)
        previous_topics = []
        if self.history is not None:
            previous_topics = self.history.get_topic_titles()
        prompt = (
            _TOPIC_INSTRUCTIONS
            + "\n\nRECENT HISTORY TO AVOID (never repeat, rephrase, or lightly disguise any of "
            "these pairs; choose a genuinely different comparison and, ideally, a different "
            "domain):\n"
            + ("; ".join(previous_topics[:30]) or "(gol - no episodes published yet)")
        )
        pool = await self.llm.complete_structured(
            _TOPIC_SYSTEM_PROMPT,
            prompt,
            ReferenceTopicPool,
            schema_name="reference_topic",
            temperature=0.65,
            max_tokens=4800,
        )
        existing_pairs = self._existing_pairs()
        selected = self.selector.select(
            pool.topics,
            existing_pairs=existing_pairs,
            limit=1,
        )
        if not selected:
            rejection_notes = self._rejection_notes(pool.topics)
            repaired = await self.llm.complete_structured(
                _TOPIC_SYSTEM_PROMPT,
                prompt
                + "\n\nREPAIR THE CANDIDATE POOL. Every previous candidate was rejected. "
                "Clear these exact failures and return new, unrelated pairs:\n"
                + rejection_notes,
                ReferenceTopicPool,
                schema_name="reference_topic_repair",
                temperature=0.0,
                max_tokens=4800,
            )
            selected = self.selector.select(
                repaired.topics,
                existing_pairs=existing_pairs,
                limit=1,
            )
            if not selected:
                raise RuntimeError(
                    "No eligible confusion-tension topic after repair: "
                    + self._rejection_notes(repaired.topics)
                )
        candidate = selected[0]
        topic = TopicSpec(
            title=candidate.title,
            comparison_left=candidate.left,
            comparison_right=candidate.right,
            angle=candidate.angle,
        )
        if self.proofreader is not None and request.language == "ro":
            topic = await self.proofreader.correct_topic(topic)
        if self.history is not None:
            self.history.add_from_topic(topic)
        return topic

    def _existing_pairs(self) -> set[str]:
        if self.history is None:
            return set()
        getter = getattr(self.history, "get_normalized_pairs", None)
        return set(getter()) if callable(getter) else set()

    def _rejection_notes(self, candidates: list[TopicCandidate]) -> str:
        notes: list[str] = []
        for candidate in candidates:
            decision = self.selector.evaluate(candidate)
            reasons = decision.reasons or ("duplicate or excluded by history",)
            notes.append(f"- {candidate.title}: {', '.join(reasons)}")
        return "\n".join(notes) or "- no structurally valid candidates"

    @staticmethod
    def _parse_override(value: str) -> TopicSpec:
        parts = re.split(r"\s+(?:vs\.?|versus)\s+", value.strip(), maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise ValueError("Topic override must use the form 'Left vs Right'")
        return TopicSpec(
            title=f"{parts[0].strip()} vs {parts[1].strip()}",
            comparison_left=parts[0].strip(),
            comparison_right=parts[1].strip(),
        )


class ReferenceResearcher:
    def __init__(self, search_provider: object, llm: object):
        self.search_provider = search_provider
        self.llm = llm
        self._scoring = ResearchService(search_provider=search_provider)

    async def generate(self, topic: TopicSpec) -> ResearchPackage:
        queries = self._scoring.build_queries(topic)[:4]
        responses = await asyncio.gather(
            *(self.search_provider.search(query, 5) for query in queries)
        )
        sources = self._scoring.deduplicate_sources(list(responses))
        facts = "\n".join(
            f"- {source.id}: {source.title}; {source.url}" for source in sources[:12]
        ) or "- No verified source results"
        result = await self.llm.complete_structured(
            _RESEARCH_SYSTEM_PROMPT,
            _RESEARCH_INSTRUCTIONS
            + f"\n\nTOPIC: {topic.title}\n"
            f"Left item: {topic.comparison_left}\n"
            f"Right item: {topic.comparison_right}\n"
            f"SOURCES (cite only these ids):\n{facts}",
            ReferenceResearchSummary,
            schema_name="reference_research",
            temperature=0.1,
            max_tokens=1200,
        )
        available_ids = {source.id for source in sources}
        research_facts = [
            fact.model_copy(update={
                "source_ids": [source_id for source_id in fact.source_ids if source_id in available_ids],
            })
            for fact in result.facts
        ]
        return ResearchPackage(
            topic=topic.title,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            facts=[
                ResearchFact(**fact.model_dump())
                for fact in research_facts
                if fact.source_ids
            ],
            sources=sources[:12],
            unresolved_questions=result.unresolved_questions,
            safety_notes=result.safety_notes,
        )


class ReferenceVerifier:
    def __init__(self, service: object):
        self.service = service

    async def verify(
        self,
        script: ReferenceScriptPackage,
        research: ResearchPackage,
        topic: TopicSpec,
    ) -> VerificationResult:
        return await self.service.verify(
            narration=script.narration_text,
            claims=script.claims,
            research=research,
            left_item=topic.comparison_left,
            right_item=topic.comparison_right,
            angle=topic.angle,
        )
