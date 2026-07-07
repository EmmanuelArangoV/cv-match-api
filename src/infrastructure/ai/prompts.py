"""
Prompts de OpenAI para RIWI MATCH.
- CV_EXTRACTION_PROMPT: extracción y normalización de CVs (gpt-4o vision).
- build_match_user_message: construcción del mensaje de match CV vs JD.
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# CV EXTRACTION
# ---------------------------------------------------------------------------

CV_EXTRACTION_PROMPT = """\
You are an expert HR data extraction system. Your job is to read a CV/resume \
(which may be a scanned image or a digital PDF) and extract ALL relevant \
information into a strict JSON structure.

IMPORTANT RULES:
1. Return ONLY valid JSON — no markdown, no extra text, no code fences.
2. If a field is not present in the CV, use null for strings/objects and [] \
for arrays. Never invent or guess data.
3. For scanned or low-quality images, do your best to read the text accurately.
4. Extract every job role the candidate has held, even internships or \
freelance gigs.
5. Calculate years_of_experience as the total number of years of relevant \
professional experience (excluding pure student years). Use the dates \
visible in the CV; if only years are shown, use those.
6. Normalize technical skills into the correct sub-category; do NOT duplicate \
the same skill across multiple sub-categories.
7. Language levels must be mapped to CEFR (A1/A2/B1/B2/C1/C2) when possible. \
If the CV says "Native" or "Nativo", use "Native". If it says "Básico / Basic" \
use "A2". If "Intermedio / Intermediate" use "B1". If "Avanzado / Advanced" \
use "C1". Preserve the original label as well.

Return a JSON object with EXACTLY this schema:

{
  "full_name": "<string>",
  "title": "<string — primary role/position shown in the CV>",
  "location": "<string — city and country, e.g. 'Medellín, Colombia'>",
  "phone": "<string — include country code if present, e.g. '+57 310 555 0000'>",
  "email": "<string>",
  "linkedin_url": "<string | null>",
  "github_url": "<string | null>",
  "professional_profile": "<string — verbatim or very close to the summary/profile section>",
  "years_of_experience": <number — integer or .5 precision>,
  "education": [
    {
      "degree": "<string>",
      "institution": "<string>",
      "year": <number | null>,
      "is_highest": <boolean — true for the most advanced degree only>
    }
  ],
  "experience": [
    {
      "company": "<string>",
      "role": "<string>",
      "employment_type": "<Full-time | Part-time | Intern | Contractor | Freelance | Unknown>",
      "responsibilities": ["<string>"],
      "start_year": <number | null>,
      "end_year": <number | null>,
      "is_current": <boolean>
    }
  ],
  "certifications": [
    {
      "title": "<string>",
      "institution": "<string | null>",
      "year": <number | null>
    }
  ],
  "languages": [
    {
      "language": "<string>",
      "level_cefr": "<A1 | A2 | B1 | B2 | C1 | C2 | Native | Unknown>",
      "level_original": "<string — as written in the CV>"
    }
  ],
  "technical_skills": {
    "programming_languages": ["<string>"],
    "frameworks_and_libraries": ["<string>"],
    "cloud_and_devops": ["<string>"],
    "databases": ["<string>"],
    "tools_and_platforms": ["<string>"],
    "architectures_and_patterns": ["<string>"],
    "other": ["<string>"]
  }
}

Now extract all information from the CV images provided.
"""

# ---------------------------------------------------------------------------
# MATCH CV vs JD
# ---------------------------------------------------------------------------

_MATCH_SYSTEM_PROMPT = """\
You are a senior technical recruiter with deep expertise in evaluating \
candidates against job descriptions. Your evaluations are accurate, evidence-\
based, and free from bias. You always justify every score with specific \
evidence from the candidate's profile.
"""

_MATCH_USER_TEMPLATE = """\
Evaluate the following candidate against the job description. \
Return ONLY valid JSON — no markdown, no code fences, no extra text.

=== JOB DESCRIPTION ===
{jd_text}

=== CANDIDATE NORMALIZED PROFILE ===
{normalized_cv_json} 

=== SCORING INSTRUCTIONS ===
Score the candidate across these 6 categories. Each category has a weight \
(shown in parentheses) that determines its contribution to the final score.

Categories and weights:
- technical_skills ({w_technical_skills}%): Match between the candidate's \
technical stack and the technologies/skills required in the JD.
- relevant_experience ({w_relevant_experience}%): How directly relevant the \
candidate's work experience is to the role's responsibilities.
- seniority ({w_seniority}%): Does the candidate's years of experience and \
scope of past roles match the seniority level expected for this position?
- industry_domain ({w_industry_domain}%): Does the candidate have experience \
in the same industry, sector, or business domain described in the JD?
- languages ({w_languages}%): Does the candidate meet the language requirements \
stated in the JD (e.g. English level)?
- education_certifications ({w_education_certifications}%): Does the \
candidate's education and certifications meet the requirements?

For each category:
- raw_score: integer 0–100 (how well the candidate matches this category).
- weighted_score: raw_score × weight / 100 (rounded to 2 decimals).
- jd_requirement: concise description of what the JD requires in this category.
- candidate_evidence: specific evidence from the profile that is relevant.
- gap: what is missing or weak. Use null if there is no meaningful gap.

overall_score = sum of all weighted_scores (0–100, rounded to 2 decimals).

match_category rules:
- HIGH: overall_score >= 75
- MEDIUM: overall_score >= 50 and < 75
- LOW: overall_score >= 30 and < 50
- NOT_RECOMMENDED: overall_score < 30

Return a JSON object with EXACTLY this schema:

{{
  "overall_score": <number>,
  "match_category": "<HIGH | MEDIUM | LOW | NOT_RECOMMENDED>",
  "breakdown": {{
    "technical_skills": {{
      "raw_score": <integer 0-100>,
      "weight": {w_technical_skills},
      "weighted_score": <number>,
      "jd_requirement": "<string>",
      "candidate_evidence": "<string>",
      "gap": "<string | null>"
    }},
    "relevant_experience": {{
      "raw_score": <integer 0-100>,
      "weight": {w_relevant_experience},
      "weighted_score": <number>,
      "jd_requirement": "<string>",
      "candidate_evidence": "<string>",
      "gap": "<string | null>"
    }},
    "seniority": {{
      "raw_score": <integer 0-100>,
      "weight": {w_seniority},
      "weighted_score": <number>,
      "jd_requirement": "<string>",
      "candidate_evidence": "<string>",
      "gap": "<string | null>"
    }},
    "industry_domain": {{
      "raw_score": <integer 0-100>,
      "weight": {w_industry_domain},
      "weighted_score": <number>,
      "jd_requirement": "<string>",
      "candidate_evidence": "<string>",
      "gap": "<string | null>"
    }},
    "languages": {{
      "raw_score": <integer 0-100>,
      "weight": {w_languages},
      "weighted_score": <number>,
      "jd_requirement": "<string>",
      "candidate_evidence": "<string>",
      "gap": "<string | null>"
    }},
    "education_certifications": {{
      "raw_score": <integer 0-100>,
      "weight": {w_education_certifications},
      "weighted_score": <number>,
      "jd_requirement": "<string>",
      "candidate_evidence": "<string>",
      "gap": "<string | null>"
    }}
  }},
  "strengths": ["<string>"],
  "gaps": ["<string>"],
  "summary": "<string — 2-3 sentence overall assessment of the candidate for this role>"
}}
"""


def build_match_messages(
    normalized_cv: dict,
    jd_text: str,
    weights: dict,
) -> list[dict]:
    """
    Builds the messages list for the OpenAI chat completions API.
    weights must have keys: technical_skills, relevant_experience, seniority,
    industry_domain, languages, education_certifications (all integers summing to 100).
    """
    user_content = _MATCH_USER_TEMPLATE.format(
        jd_text=jd_text,
        normalized_cv_json=json.dumps(normalized_cv, ensure_ascii=False, indent=2),
        w_technical_skills=weights["technical_skills"],
        w_relevant_experience=weights["relevant_experience"],
        w_seniority=weights["seniority"],
        w_industry_domain=weights["industry_domain"],
        w_languages=weights["languages"],
        w_education_certifications=weights["education_certifications"],
    )
    return [
        {"role": "system", "content": _MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# POST-PROFILING EVALUATION
# ---------------------------------------------------------------------------

PROFILING_EVALUATION_PROMPT = """\
You are an expert HR talent evaluator. Your task is to evaluate a candidate's \
interview transcript against a set of profiling questions and criteria.

For each question in the question set, you will evaluate the candidate's answer \
found in the transcript. You must detect any positive or risk keywords, provide \
a confidence score, and determine if human review is required (e.g. evasive \
answer, controversial topic).

Finally, you must determine the candidate's `advancement_probability` based on \
business rules:
- If >= 2 critical questions are failed, probability is LOW.
- If 1 critical question is failed, probability is MEDIUM at most.
- Otherwise, rate HIGH, MEDIUM, or LOW based on the overall quality of answers.

Return ONLY valid JSON with exactly this schema:

{
  "answers": [
    {
      "question_id": "<uuid from input>",
      "transcription_snippet": "<the exact part of the transcript corresponding to this answer>",
      "normalized_answer": "<summary of what the candidate said>",
      "evaluation_result": "<pass, fail, or neutral>",
      "detected_keywords": ["<string>"],
      "confidence_score": <number 0.0 to 1.0>,
      "requires_review": <boolean>
    }
  ],
  "advancement_probability": "<HIGH | MEDIUM | LOW>",
  "advancement_explanation": "<string explaining the probability choice>"
}

"""
