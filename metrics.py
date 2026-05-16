"""
Bingus Chef — Metrics & Reliability Tester
===========================================
Measures:
  1. JSON Parsing Success Rate (%)  — AI responses that parse as valid JSON
  2. Recipe Adherence Rate (%)      — AI follows Tool-First Rules & ingredient constraints
  3. API Response Latency (s)       — Typhoon v2.5 processing time via FastAPI

Usage:
  python metrics.py                  # test against http://localhost:5000
  python metrics.py --url https://binguschef.vercel.app  # test deployed instance
  python metrics.py --count 200      # run 200 test iterations (default 100)
"""

import argparse, json, sys, time, re, os
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError
from typing import Optional

REPORT_WIDTH = 72

# ── Test scenarios ──────────────────────────────────────────────────────────

TEST_CASES = [
    # (label, tools, ingredients, method, notes)
    (
        "Limited kitchen — pot + stove only, simple proteins + veggies",
        ["Pot", "Stove", "Knife", "Cutting board"],
        "Eggs, onion, garlic, rice, chicken thigh, cabbage, fish sauce, soy sauce, oil",
        "",
        "",
    ),
    (
        "Full kitchen — oven, air-fryer, sous-vide, all tools",
        ["Oven", "Stove", "Pot", "Pan", "Air fryer", "Rice cooker",
         "Grill", "Microwave", "Slow cooker", "Sous-vide", "Steamer",
         "Knife", "Cutting board", "Mixer"],
        "Chicken breast, salmon, potato, carrot, onion, garlic, bell pepper, "
        "broccoli, egg, butter, cream, cheese, flour, rice, pasta, oil, "
        "salt, pepper, soy sauce, fish sauce, sugar, oyster sauce, basil, chili",
        "",
        "",
    ),
    (
        "No heat source — only knife + board, cold dishes only",
        ["Knife", "Cutting board", "Bowl"],
        "Lettuce, tomato, cucumber, onion, canned tuna, egg, mayonnaise, "
        "bread, lime, fish sauce, chili, sugar, cabbage, carrot",
        "",
        "",
    ),
    (
        "Stir-fry method requested — pan + stove available",
        ["Pan", "Stove", "Knife", "Cutting board"],
        "Chicken thigh, garlic, chili, basil, oyster sauce, soy sauce, "
        "fish sauce, sugar, oil, rice",
        "Stir-fry",
        "Spicy, not too salty",
    ),
    (
        "Soup method requested — pot + stove available",
        ["Pot", "Stove", "Knife", "Cutting board"],
        "Pork bones, daikon, carrot, onion, garlic, salt, pepper, "
        "spring onion, cilantro, rice noodles, bean sprouts",
        "Boil",
        "Clear soup",
    ),
    (
        "Bake requested with oven available",
        ["Oven", "Stove", "Pan", "Knife", "Cutting board", "Mixer", "Baking tray"],
        "Chicken breast, potato, carrot, onion, garlic, butter, "
        "cream, cheese, salt, pepper, oil, rosemary",
        "Bake",
        "",
    ),
    (
        "Bake requested WITHOUT oven — should reject or offer alternatives",
        ["Pan", "Stove", "Knife", "Cutting board"],
        "Chicken breast, potato, carrot, onion, garlic, butter, "
        "salt, pepper, oil",
        "Bake",
        "",
    ),
    (
        "Rice cooker only — simple steamed/rice dishes",
        ["Rice cooker"],
        "Rice, egg, Chinese sausage, soy sauce, spring onion, garlic, oil",
        "",
        "",
    ),
    (
        "Deep-fry requested — pan + stove + air fryer",
        ["Pan", "Stove", "Air fryer", "Knife", "Cutting board"],
        "Chicken wings, flour, egg, breadcrumbs, salt, pepper, "
        "garlic powder, oil, potato",
        "Deep-fry",
        "Crispy",
    ),
    (
        "Very few ingredients — simple dish guaranteed",
        ["Pan", "Stove", "Knife", "Cutting board"],
        "Eggs, rice, fish sauce",
        "",
        "Simple, quick",
    ),
]


# ── Helpers ─────────────────────────────────────────────────────────────────

def api_post(url: str, path: str, body: dict) -> Optional[dict]:
    """POST JSON to endpoint, return parsed response or None."""
    full_url = f"{url}{path}"
    data = json.dumps(body).encode("utf-8")
    req = Request(full_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        t0 = time.perf_counter()
        resp = urlopen(req, timeout=60)
        t1 = time.perf_counter()
        raw = resp.read().decode("utf-8")
        latency = t1 - t0
        try:
            parsed = json.loads(raw)
            return {"ok": True, "data": parsed, "latency": latency, "raw": raw}
        except json.JSONDecodeError:
            return {"ok": False, "data": None, "latency": latency, "raw": raw[:500]}
    except URLError as e:
        return {"ok": False, "data": None, "latency": None, "raw": str(e)}
    except Exception as e:
        return {"ok": False, "data": None, "latency": None, "raw": str(e)}


def check_adherence(result: dict, tools: list, method: str, notes: str) -> dict:
    """Verify the AI output follows Tool-First Rules and method constraints.
    Returns dict with pass/fail + list of issues found.
    """
    issues = []
    data = result.get("data")
    if not data:
        return {"pass": False, "issues": ["No data returned"]}

    suggestions = data.get("suggestions", [])
    if not suggestions:
        # detail endpoint has different shape
        suggestions = [data] if data.get("name") else []

    has_oven = any("oven" in t.lower() for t in tools)
    has_stove = any(t.lower() in ("stove", "electric stove", "เตา", "เตาไฟฟ้า")
                    for t in tools)
    has_pot = any("pot" in t.lower() or "หม้อ" in t for t in tools)
    has_heat = has_oven or has_stove or has_pot or any(
        t.lower() in ("rice cooker", "slow cooker", "air fryer", "pan",
                      "microwave", "grill", "steamer", "หม้อหุงข้าว",
                      "หม้อทอดไร้น้ำมัน", "กระทะ", "เตาย่าง", "เตาอบ")
        for t in tools
    )
    has_knife = any("knife" in t.lower() or "มีด" in t for t in tools)

    for i, s in enumerate(suggestions):
        name = s.get("name", f"#{i + 1}")
        desc = (s.get("description", "") + " " + name).lower()
        ing = " ".join(s.get("ingredients", [])).lower()

        # RULE: No oven recipe if user has no oven
        if not has_oven:
            for keyword in ["oven", "bake", "roast", "อบ", "ปิ้ง"]:
                if keyword in desc or keyword in ing:
                    issues.append(
                        f"[{name}] recommends oven/bake but user has no oven"
                    )

        # RULE: No baking method if bake requested and no oven
        if method.lower() == "bake" and not has_oven:
            issues.append(
                f"[suggestions] method='Bake' but user has no oven — "
                f"should either reject or offer alternatives"
            )

        # RULE: No hot dish if no heat source
        if not has_heat:
            for keyword in ["stir-fry", "fry", "boil", "steam", "grill",
                            "cook", "heat", "pan", "simmer", "sauté",
                            "ผัด", "ทอด", "ต้ม", "นึ่ง", "ย่าง"]:
                if keyword in desc or keyword in ing:
                    issues.append(
                        f"[{name}] is a hot dish but user has no heat source"
                    )

        # RULE: Method preference is respected
        if method and method.lower() != "":
            method_lower = method.lower()
            method_words = {
                "stir-fry": ["stir-fry", "ผัด"],
                "deep-fry": ["deep-fry", "deep fry", "ทอด"],
                "boil": ["boil", "ต้ม"],
                "bake": ["bake", "roast", "อบ"],
                "grill": ["grill", "ย่าง"],
                "steam": ["steam", "นึ่ง"],
            }
            expected_keywords = method_words.get(method_lower, [method_lower])
            if not any(kw in desc or kw in ing for kw in expected_keywords):
                issues.append(
                    f"[{name}] method='{method}' but dish doesn't match"
                )

        # RULE: Has calorie estimate
        if not s.get("calories"):
            issues.append(f"[{name}] missing calorie estimate")

        # RULE: Missing array exists (even if empty)
        if "missing" not in s:
            issues.append(f"[{name}] missing 'missing' field")

    return {"pass": len(issues) == 0, "issues": issues}


def check_detail_adherence(result: dict, tools: list, method: str) -> dict:
    """Verify the /detail response follows the rules."""
    issues = []
    data = result.get("data")
    if not data:
        return {"pass": False, "issues": ["No data returned"]}

    has_oven = any("oven" in t.lower() for t in tools)
    has_heat = any(
        t.lower() in ("stove", "electric stove", "oven", "pot", "pan",
                      "rice cooker", "slow cooker", "air fryer",
                      "microwave", "grill", "steamer", "เตา", "เตาไฟฟ้า",
                      "หม้อ", "กระทะ", "เตาอบ", "หม้อหุงข้าว", "หม้อทอดไร้น้ำมัน")
        for t in tools
    )

    name = data.get("name", "unknown")
    steps_text = " ".join(
        s.get("text", "") for s in data.get("prep_steps", [])
    ) + " " + " ".join(
        s.get("text", "") for s in data.get("cook_steps", [])
    )
    steps_text = steps_text.lower()

    # Must have nutrition
    nutrition = data.get("nutrition", {})
    required_nutrition = ["calories", "protein", "carbs", "fat", "fiber"]
    for key in required_nutrition:
        if key not in nutrition:
            issues.append(f"[{name}] missing nutrition.{key}")

    # Must have ingredients
    if not data.get("ingredients"):
        issues.append(f"[{name}] missing ingredients list")

    # Must have prep_steps and cook_steps (or combined steps)
    if not data.get("prep_steps") and not data.get("cook_steps") and not data.get("steps"):
        issues.append(f"[{name}] missing steps (prep_steps, cook_steps, or steps)")

    # Must not reference oven if user has no oven
    if not has_oven:
        for keyword in ["preheat oven", "oven", "bake at", "roast at", "อบ", "เตาอบ"]:
            if keyword in steps_text:
                issues.append(f"[{name}] references oven but user has none")

    # Must not use heat if no heat source
    if not has_heat:
        for keyword in ["heat", "stove", "boil", "fry", "simmer", "grill",
                        "pan", "cook over", "เตา", "ตั้งไฟ", "ผัด", "ทอด", "ต้ม"]:
            if keyword in steps_text:
                issues.append(f"[{name}] uses heat but user has no heat source")

    return {"pass": len(issues) == 0, "issues": issues}


def print_sep(char="="):
    print(char * REPORT_WIDTH)


def print_header(text):
    print_sep()
    print(f"  {text}")
    print_sep()


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bingus Chef Metrics Tester")
    parser.add_argument("--url", default="http://localhost:5000",
                        help="Base URL of the API (default: http://localhost:5000)")
    parser.add_argument("--count", type=int, default=100,
                        help="Number of test iterations (default: 100)")
    args = parser.parse_args()

    BASE = args.url.rstrip("/")
    TOTAL = args.count
    test_cases = TEST_CASES * max(1, TOTAL // len(TEST_CASES) + 1)
    test_cases = test_cases[:TOTAL]

    print(f"\n  Bingus Chef — Metrics Report")
    print(f"  Generated: {datetime.now().isoformat()}")
    print(f"  Target:    {BASE}")
    print(f"  Samples:   {TOTAL}")
    print()

    # ── Accumulators ──
    suggest_ok = 0
    suggest_total = 0
    suggest_latencies = []
    suggest_json_failures = 0

    detail_ok = 0
    detail_total = 0
    detail_latencies = []
    detail_json_failures = 0

    adherence_issues = 0
    adherence_checks = 0

    suggestion_counts = []

    # ── Run tests ──
    print_header("Running tests...")

    for idx, (label, tools, ingredients, method, notes) in enumerate(test_cases):
        if idx % 10 == 0:
            print(f"  Progress: {idx}/{TOTAL}")

        # ── /suggest ──
        suggest_total += 1
        result = api_post(BASE, "/suggest", {
            "ingredients": ingredients,
            "tools": ", ".join(tools),
            "method": method,
            "notes": notes,
            "locale": "en",
        })

        if result and result.get("ok"):
            suggest_ok += 1
            if result.get("latency") is not None:
                suggest_latencies.append(result["latency"])
            suggestions = result["data"].get("suggestions", [])
            suggestion_counts.append(len(suggestions))

            # Adherence check
            adherence_checks += 1
            ad = check_adherence(result, tools, method, notes)
            if not ad["pass"]:
                adherence_issues += 1
        else:
            suggest_json_failures += 1
            if result and result.get("latency") is not None:
                suggest_latencies.append(result["latency"])
            suggestions = []
            suggestion_counts.append(0)

        # ── /detail (pick first suggestion if available) ──
        if suggestions:
            detail_total += 1
            r = suggestions[0]
            d_result = api_post(BASE, "/detail", {
                "name": r.get("name", ""),
                "ingredients": ingredients,
                "tools": ", ".join(tools),
                "method": method,
                "notes": notes,
                "locale": "en",
            })

            if d_result and d_result.get("ok"):
                detail_ok += 1
                if d_result.get("latency") is not None:
                    detail_latencies.append(d_result["latency"])

                # Adherence check for detail
                adherence_checks += 1
                dad = check_detail_adherence(d_result, tools, method)
                if not dad["pass"]:
                    adherence_issues += 1
            else:
                detail_json_failures += 1
                if d_result and d_result.get("latency") is not None:
                    detail_latencies.append(d_result["latency"])

    # ── Report ──
    print(f"\n  Progress: {TOTAL}/{TOTAL} complete")
    print()

    # 1. JSON Parsing Success Rate
    print_header("1. JSON Parsing Success Rate")
    total_requests = suggest_total + detail_total
    total_ok = suggest_ok + detail_ok
    total_fail = suggest_json_failures + detail_json_failures
    json_rate = (total_ok / total_requests * 100) if total_requests else 0

    print(f"  /suggest calls:    {suggest_total}")
    print(f"    ✓ Parsed OK:     {suggest_ok}")
    print(f"    ✗ Parse failed:  {suggest_json_failures}")
    suggest_rate = (suggest_ok / suggest_total * 100) if suggest_total else 0
    print(f"    Success rate:    {suggest_rate:.1f}%")
    print()
    print(f"  /detail calls:     {detail_total}")
    print(f"    ✓ Parsed OK:     {detail_ok}")
    print(f"    ✗ Parse failed:  {detail_json_failures}")
    detail_rate = (detail_ok / detail_total * 100) if detail_total else 0
    print(f"    Success rate:    {detail_rate:.1f}%")
    print()
    print(f"  ─────────────────────────────")
    print(f"  OVERALL JSON Rate: {json_rate:.1f}%  "
          f"({total_ok}/{total_requests})")

    # 2. Recipe Adherence Rate
    print_header("2. Recipe Adherence Rate")
    adhere_rate = max(0, (1 - adherence_issues / max(1, adherence_checks)) * 100)
    print(f"  Tool/Ingredient rule checks: {adherence_checks}")
    print(f"    ✓ Passed:         {adherence_checks - adherence_issues}")
    print(f"    ✗ Rule violations:{adherence_issues}")
    print()
    print(f"  ─────────────────────────────")
    print(f"  ADHERENCE Rate:    {adhere_rate:.1f}%")

    # 3. Latency
    print_header("3. API Response Latency")

    def fmt_lat(lats):
        if not lats:
            return "N/A", "N/A", "N/A"
        avg = sum(lats) / len(lats)
        mn = min(lats)
        mx = max(lats)
        return f"{avg:.2f}s", f"{mn:.2f}s", f"{mx:.2f}s"

    s_avg, s_min, s_max = fmt_lat(suggest_latencies)
    d_avg, d_min, d_max = fmt_lat(detail_latencies)
    all_lat = suggest_latencies + detail_latencies
    a_avg, a_min, a_max = fmt_lat(all_lat)

    print(f"  ── /suggest ─────────────────")
    print(f"    Samples:   {len(suggest_latencies)}")
    print(f"    Average:   {s_avg}")
    print(f"    Min:       {s_min}")
    print(f"    Max:       {s_max}")
    print()
    print(f"  ── /detail ──────────────────")
    print(f"    Samples:   {len(detail_latencies)}")
    print(f"    Average:   {d_avg}")
    print(f"    Min:       {d_min}")
    print(f"    Max:       {d_max}")
    print()
    print(f"  ── Combined ─────────────────")
    print(f"    Samples:   {len(all_lat)}")
    print(f"    Average:   {a_avg}")
    print(f"    Min:       {a_min}")
    print(f"    Max:       {a_max}")

    # 4. Extra stats
    print_header("4. Extra Statistics")
    if suggestion_counts:
        avg_sug = sum(suggestion_counts) / len(suggestion_counts)
        print(f"  Avg suggestions per request: {avg_sug:.1f}")
        print(f"  Min: {min(suggestion_counts)}, Max: {max(suggestion_counts)}")

    print()
    print_sep()
    print(f"  TEST COMPLETE — {TOTAL} iterations, {datetime.now().isoformat()}")
    print_sep()
    print()

    # Return exit code based on results
    if json_rate < 95:
        print("  ⚠ WARNING: JSON parsing rate below 95%")
        sys.exit(1)
    if adhere_rate < 90:
        print("  ⚠ WARNING: Recipe adherence below 90%")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
