"""
Tests for the local benchmark harness.

The reply parser is what decides what a model actually said, so it is the piece
worth pinning down: everything downstream of it -- the action posted to the
adapter, the score, the ranking -- is only as trustworthy as this.
"""

import pytest

from tools.bench_local import (
    Budget,
    strip_thoughts,
    BudgetExceeded,
    QuotaExhausted,
    RateLimitError,
    RateLimiter,
    aggregate,
    action_health,
    build_system_prompt,
    health_rates,
    health_totals,
    health_with_rates,
    metric_means,
    parse_reply,
    parse_seeds,
)


# ── Reply parsing ─────────────────────────────────────────────────────────────

def test_parses_the_requested_format():
    action, reasoning = parse_reply("REASON: cheap reach first\nACTION: Air1")
    assert action == "Air1"
    assert reasoning == "cheap reach first"


@pytest.mark.parametrize("word", ["null", "NULL", "none", "pass", "wait", "skip", "-"])
def test_pass_words_become_a_null_action(word):
    """
    A null action is a legitimate move, not a parse failure -- the harness must
    not turn "wait and bank DNA" into a rejected action.
    """
    action, _ = parse_reply(f"REASON: banking\nACTION: {word}")
    assert action is None


@pytest.mark.parametrize("raw", [
    "ACTION: `Air1`",
    'ACTION: "Air1"',
    "ACTION: Air1.",
    'ACTION: {"action": "Air1"}',
    "**ACTION:** Air1",
])
def test_strips_the_decoration_models_add(raw):
    action, _ = parse_reply(f"REASON: reach\n{raw}")
    assert action == "Air1"


def test_falls_back_to_the_last_line_without_an_action_label():
    """Weaker models narrate and then name the trait. Take the trait."""
    action, reasoning = parse_reply("I want more reach before symptoms.\nAir1")
    assert action == "Air1"
    assert "reach" in reasoning


def test_keeps_devolve_actions_intact():
    action, _ = parse_reply("REASON: refund\nACTION: devolve:Coughing")
    assert action == "devolve:Coughing"


def test_free_text_is_passed_through_for_the_adapter_to_match():
    """
    Normalisation lives in adapter.py and matches trait names inside free text.
    Parsing must not pre-empt it by discarding text it cannot read, or models
    get scored on format compliance the real harness forgives.
    """
    action, _ = parse_reply("lets go with cold resist")
    assert action == "lets go with cold resist"


def test_empty_reply_is_a_pass_not_a_crash():
    assert parse_reply("") == (None, "")


def test_runaway_reply_is_capped():
    action, reasoning = parse_reply("ACTION: " + "x" * 5000)
    assert len(action) <= 500
    assert len(reasoning) <= 500


# ── Spend guards ──────────────────────────────────────────────────────────────

def test_call_ceiling_stops_the_run():
    budget = Budget(max_calls=2, max_cost=0, price_in=0, price_out=0)
    budget.guard(); budget.record()
    budget.guard(); budget.record()
    with pytest.raises(BudgetExceeded):
        budget.guard()


def test_cost_ceiling_stops_the_run():
    budget = Budget(max_calls=0, max_cost=1.00, price_in=5.00, price_out=25.00)
    budget.guard()
    budget.record(tokens_in=100_000, tokens_out=30_000)   # $0.50 + $0.75
    with pytest.raises(BudgetExceeded):
        budget.guard()


def test_cost_ceiling_is_inert_without_prices():
    """An unpriced model must not be silently treated as free-and-capped."""
    budget = Budget(max_calls=0, max_cost=1.00, price_in=0, price_out=0)
    budget.record(tokens_in=10_000_000, tokens_out=10_000_000)
    budget.guard()


def test_cached_input_is_billed_at_a_tenth():
    budget = Budget(max_calls=0, max_cost=0, price_in=10.00, price_out=0)
    budget.record(tokens_in=0, cached=1_000_000)
    assert budget.cost == pytest.approx(1.00)


# ── Inline reasoning ──────────────────────────────────────────────────────────
#
# Every case below is a real reply from the gemma-4-31b-it sweep, where 305 of
# 729 attempted moves were truncated mid-thought. They were recorded as actions
# the environment could not read -- the bucket meaning "the parser failed" --
# which hid the warning that names the real cause: the model ran out of room
# before it answered.

TRUNCATED = [
    "<thought>\nI should boost transmission early.\n</thought>",
    "<thought>\nWait, let me think.</thought>",
    "<thought>\nActually, looking at the reward function: `infected_fraction + dead_fraction</thought>",
    "<thought>\nLet's see if `null` is better. If I `</thought>",
    "<thought>\nPulmonaryOedema`, `Pul</thought>",
    "<thought>\nDi",                                  # never closed at all
]


@pytest.mark.parametrize("reply", TRUNCATED)
def test_a_reply_that_is_all_reasoning_counts_as_no_reply(reply):
    """Empty action *and* empty reasoning is what the episode loop records as
    `unparsed`, which is the bucket that fires the truncation warning."""
    action, reasoning = parse_reply(reply)
    assert action is None
    assert reasoning.strip() == ""


def test_a_thought_block_does_not_swallow_the_answer_that_follows_it():
    reply = "<thought>\nAir2 is the cheap reach.\n</thought>\nREASON: cheap reach\nACTION: Air2"
    assert parse_reply(reply) == ("Air2", "cheap reach")


@pytest.mark.parametrize("tag", ["thought", "think", "thinking"])
def test_the_common_tag_spellings_are_all_stripped(tag):
    assert strip_thoughts(f"<{tag}>reasoning</{tag}>ACTION: Air1").strip() == "ACTION: Air1"


def test_a_reply_with_no_reasoning_block_is_left_alone():
    """The strip must be inert for every model that does not reason inline."""
    for reply in ("REASON: x\nACTION: Air1", "Air1", "", "a < b and c > d"):
        assert strip_thoughts(reply) == reply


def test_a_deliberate_null_is_still_told_apart_from_a_truncated_reply():
    """Both reach the environment as no action and they mean opposite things:
    one is a legitimate move, the other is a turn the model never took."""
    action, reasoning = parse_reply("REASON: bank DNA for Air3\nACTION: null")
    assert action is None and reasoning.strip()          # -> passed
    action, reasoning = parse_reply("<thought>\nhmm</thought>")
    assert action is None and not reasoning.strip()      # -> unparsed


# ── Crash safety ──────────────────────────────────────────────────────────────
#
# These two drive `main()` end to end against a running adapter, because the
# property under test is where the record is written relative to the episode
# loop -- which only the real wiring can show. Skipped, not failed, when no
# adapter is up: the rest of the suite must stay runnable without one.

def _adapter_up() -> bool:
    from tools.bench_local import EnvClient
    return EnvClient("http://localhost:8765").health()


needs_adapter = pytest.mark.skipif(
    not _adapter_up(), reason="no adapter on :8765 (python adapter.py)"
)



@needs_adapter
def test_a_crash_mid_sweep_keeps_the_episodes_that_finished(tmp_path, monkeypatch):
    """
    The record used to be written only after the final episode, so an
    unhandled error on episode four destroyed the three that had already
    finished -- four hours of a paid sweep, gone to a dropped TCP connection.
    A failure must now stop the run the way a tripped guard does.
    """
    from tools import bench_local
    import json

    calls = {"n": 0}
    real = bench_local.run_episode

    def flaky(env, agent, seed, budget, args):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ConnectionResetError(10054, "forcibly closed by the remote host")
        return real(env, agent, seed, budget, args)

    monkeypatch.setattr(bench_local, "run_episode", flaky)
    monkeypatch.setattr(bench_local.sys, "argv", [
        "bench_local.py", "--model", "policy/random",
        "--seeds", "India,China,USA,Brazil",
        "--max-steps", "40", "--runs-dir", str(tmp_path), "--quiet",
    ])
    bench_local.main()

    written = list(tmp_path.glob("*/run.json"))
    assert len(written) == 1, "one run_id for the sweep, not one per episode"
    record = json.loads(written[0].read_text(encoding="utf-8"))
    assert record["result"]["episodes_completed"] == 2
    assert [ep["seed"] for ep in record["episodes"]] == ["India", "China"]
    assert record["result"]["stopped"].startswith("error: ConnectionResetError")


@needs_adapter
def test_each_finished_episode_is_checkpointed_as_it_lands(tmp_path, monkeypatch):
    """Not just saved on the way out: a hard kill must not cost them either."""
    from tools import bench_local
    import json

    seen = []
    real = bench_local.run_episode

    def watch(env, agent, seed, budget, args):
        # What is on disk *before* this episode runs is what the previous one left.
        found = list(tmp_path.glob("*/run.json"))
        seen.append(
            json.loads(found[0].read_text(encoding="utf-8"))["result"]["episodes_completed"]
            if found else 0
        )
        return real(env, agent, seed, budget, args)

    monkeypatch.setattr(bench_local, "run_episode", watch)
    monkeypatch.setattr(bench_local.sys, "argv", [
        "bench_local.py", "--model", "policy/random", "--seeds", "India,China,USA",
        "--max-steps", "40", "--runs-dir", str(tmp_path), "--quiet",
    ])
    bench_local.main()
    assert seen == [0, 1, 2], f"record should grow by one per episode, saw {seen}"


# ── Network failures ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("exc", [
    __import__("http.client", fromlist=["x"]).RemoteDisconnected(
        "Remote end closed connection without response"),
    ConnectionResetError(10054, "forcibly closed by the remote host"),
    __import__("http.client", fromlist=["x"]).BadStatusLine("''"),
    TimeoutError("timed out"),
])
def test_a_dropped_connection_is_retryable_rather_than_fatal(monkeypatch, exc):
    """
    urllib wraps what `request()` raises but re-raises whatever
    `getresponse()` throws, so a connection dropped mid-response arrives as a
    bare RemoteDisconnected rather than a URLError. Uncaught it escaped the
    retry loop, escaped run_episode, and ended a four-hour sweep on episode
    four -- destroying the three that had finished.
    """
    from tools import bench_local

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(bench_local.urllib.request, "urlopen", boom)
    with pytest.raises(bench_local.TransientAgentError):
        bench_local._post_json("https://example.com/v1", {}, timeout=5)


def test_a_transient_network_failure_is_retried_to_the_limit(monkeypatch):
    """Retried, and only fatal once the retries are spent."""
    from tools import bench_local
    calls = []

    class Flaky(bench_local._PromptedAgent):
        def _call(self, user):
            calls.append(user)
            raise bench_local.TransientAgentError("dropped")

    agent = Flaky("m", "sys", Budget(max_calls=0, max_cost=0, price_in=0, price_out=0),
                  retries=2)
    monkeypatch.setattr(bench_local.time, "sleep", lambda _s: None)
    with pytest.raises(bench_local.FatalAgentError):
        agent.complete("go")
    assert len(calls) == 3          # the first attempt plus two retries


# ── Rate pacing ───────────────────────────────────────────────────────────────
#
# The limiter is tested through `_delay`, with timestamps placed by hand, so a
# test of a sixty-second window does not take sixty seconds.

def test_pacing_is_off_unless_asked_for():
    """A paid key must not pay a pacing cost it never asked for."""
    limiter = RateLimiter()
    assert not limiter.active
    limiter.wait()                              # returns at once, no sleep
    assert limiter.waited == 0.0


def test_the_request_window_holds_a_call_back_once_it_is_full():
    limiter = RateLimiter(rpm=10)
    now = 1000.0
    # Chronological, as `wait` appends them: oldest first.
    limiter._calls = [now - 45 + 5 * i for i in range(10)]
    delay = limiter._delay(now)
    assert delay > 0
    # The oldest is 45s old, so the window frees up 15s from now.
    assert delay == pytest.approx(15.0, abs=0.01)


def test_a_call_is_admitted_once_the_window_has_drained():
    limiter = RateLimiter(rpm=10)
    now = 1000.0
    limiter._calls = [now - 61 - i for i in range(10)]    # all older than a minute
    assert limiter._delay(now) == 0
    assert limiter._calls == []                           # pruned


def test_the_token_window_binds_where_the_request_window_does_not():
    """Gemma's free tier allows 30 rpm but only 16K tpm, and one turn of this
    benchmark costs ~1.8K -- so tokens run out first, at about 9 calls."""
    limiter = RateLimiter(rpm=30, tpm=16_000)
    now = 1000.0
    limiter._calls = [now - 9 + i for i in range(9)]           # well inside 30 rpm
    limiter._tokens = [(now - 9 + i, 1800) for i in range(9)]  # 16.2K in the window
    limiter.record(1800)
    assert limiter._delay(now) > 0, "16.2K + 1.8K exceeds 16K and must wait"


def test_the_first_call_is_never_paced_on_tokens():
    """What a request costs is only known once it is made."""
    limiter = RateLimiter(tpm=16_000)
    assert limiter._delay(1000.0) == 0


def test_recording_zero_tokens_does_not_enter_the_window():
    limiter = RateLimiter(tpm=16_000)
    limiter.record(0)
    assert limiter._tokens == []


def test_the_limiter_describes_both_limits_for_the_guards_line():
    assert RateLimiter(rpm=8).describe() == "8 rpm"
    assert RateLimiter(rpm=30, tpm=16_000).describe() == "30 rpm + 16000 tpm"


# ── Rate-limit responses ──────────────────────────────────────────────────────

def _openai_agent(monkeypatch, body, status):
    from tools import bench_local
    agent = bench_local.OpenAICompatAgent(
        "gemma-4-31b", "system", Budget(max_calls=0, max_cost=0, price_in=0, price_out=0),
        retries=0, base_url="https://example.com/v1", api_key="k",
        temperature=0.0, max_tokens=1024,
    )
    monkeypatch.setattr(bench_local, "_post_json", lambda *a, **k: (body, status))
    return agent


def test_a_per_minute_limit_is_retried_not_fatal(monkeypatch):
    agent = _openai_agent(monkeypatch, '{"error":{"message":"Quota exceeded for requests"}}', 429)
    with pytest.raises(RateLimitError):
        agent._call("go")


def test_a_daily_quota_stops_the_run_instead_of_sleeping_out_the_retries(monkeypatch):
    """Waiting cannot clear a per-day quota. Stopping keeps the episodes that
    finished; retrying just burns the backoff and then fails anyway."""
    body = '{"error":{"message":"quota metric GenerateRequestsPerDayPerProject-FreeTier"}}'
    agent = _openai_agent(monkeypatch, body, 429)
    with pytest.raises(QuotaExhausted):
        agent._call("go")


def test_a_daily_quota_is_fatal_so_the_episode_loop_stops_cleanly():
    """QuotaExhausted must be caught by the same handler that stops a run, or
    the guard is decorative."""
    from tools.bench_local import FatalAgentError
    assert issubclass(QuotaExhausted, FatalAgentError)
    assert issubclass(RateLimitError, Exception)


# ── Manifest wiring ───────────────────────────────────────────────────────────

def test_metrics_come_from_the_manifest(tmp_path):
    manifest = {
        "scoring": {
            "primary_metric": "victory_progress",
            "metrics": [
                {"name": "victory_progress", "type": "terminal_field", "field": "victory_progress"},
                {"name": "missing", "type": "terminal_field", "field": "not_reported"},
            ],
        }
    }
    episodes = [{"score": {"victory_progress": 0.5}}, {"score": {"victory_progress": 1.0}}]
    rows = dict(aggregate(manifest, episodes))
    assert rows["victory_progress"].startswith("0.7500")
    assert rows["missing"] == "n/a"


# ── Spread ────────────────────────────────────────────────────────────────────

SPREAD_MANIFEST = {"scoring": {"primary_metric": "victory_progress", "metrics": [
    {"name": "victory_progress", "type": "terminal_field", "field": "victory_progress"},
]}}


def _episodes(*values):
    return [{"score": {"victory_progress": v}} for v in values]


def test_a_mean_is_recorded_with_the_spread_around_it():
    """A mean published alone gets compared as though it were exact."""
    stat = metric_means(SPREAD_MANIFEST, _episodes(0.8, 0.9, 1.0))["victory_progress"]
    assert stat["mean"] == pytest.approx(0.9)
    assert stat["sd"] == pytest.approx(0.1)
    assert stat["sem"] == pytest.approx(0.057735, abs=1e-5)
    low, high = stat["ci95"]
    assert low == pytest.approx(0.65159, abs=1e-4)      # t(df=2) = 4.303
    assert high == pytest.approx(1.14841, abs=1e-4)


def test_the_interval_uses_students_t_not_the_normal_approximation():
    """At ten seeds the normal 1.96 understates the interval by about 15%, and
    that is exactly the margin that makes two tied models look ranked."""
    values = [0.805, 0.910, 0.867, 0.834, 0.881, 0.849, 0.896, 0.822, 0.873, 0.858]
    stat = metric_means(SPREAD_MANIFEST, _episodes(*values))["victory_progress"]
    half = stat["ci95"][1] - stat["mean"]
    assert half == pytest.approx(2.262 * stat["sem"], rel=1e-3)
    assert half > 1.96 * stat["sem"]


def test_a_single_episode_has_no_spread_rather_than_a_spread_of_zero():
    """0.0 would read as a model that scored identically every time."""
    stat = metric_means(SPREAD_MANIFEST, _episodes(0.9))["victory_progress"]
    assert stat["mean"] == pytest.approx(0.9)
    assert stat["sd"] is None and stat["sem"] is None and stat["ci95"] is None


def test_the_terminal_summary_shows_the_interval_beside_the_mean():
    row = dict(aggregate(SPREAD_MANIFEST, _episodes(0.8, 0.9, 1.0)))["victory_progress"]
    assert row.startswith("0.9000")
    assert "sd 0.1000" in row and "95% CI [0.6516, 1.1484]" in row


def test_a_metric_with_no_values_still_reports_no_spread():
    stat = metric_means(SPREAD_MANIFEST, [{"score": {"outcome": None}}])["victory_progress"]
    assert stat["mean"] is None and stat["ci95"] is None


# ── Action health ─────────────────────────────────────────────────────────────

def _health(**counts):
    base = dict(accepted=0, rejected_unknown=0, rejected_illegal=0,
                passed=0, auto_passed=0, unparsed=0)
    base.update(counts)
    return base


def test_rejections_are_reported_as_a_share_of_what_was_attempted():
    """`103 illegal` means something very different beside 393 accepted than
    beside 3900, and the count alone does not say which."""
    rates = health_rates(_health(accepted=393, rejected_illegal=103,
                                 rejected_unknown=2, auto_passed=2634))
    assert rates["attempted"] == 498
    assert rates["rejected_rate"] == pytest.approx(0.2108, abs=1e-4)
    assert rates["illegal_rate"] == pytest.approx(0.2068, abs=1e-4)
    assert rates["unreadable_rate"] == pytest.approx(0.004, abs=1e-3)


def test_a_run_that_attempted_nothing_has_no_rate_rather_than_a_clean_one():
    """The `pass` policy attempts no move at all; 0.0 would claim a clean record."""
    rates = health_rates(_health(passed=6000))
    assert rates["attempted"] == 0
    assert rates["rejected_rate"] is None and rates["illegal_rate"] is None


def test_the_share_appears_in_the_printed_actions_line():
    episodes = [{"health": _health(accepted=393, rejected_illegal=103,
                                   rejected_unknown=2, auto_passed=2634)}]
    line, _ = action_health(episodes)
    assert "105 rejected — 21% of attempted" in line
    assert "103 illegal moves" in line


def test_illegal_moves_do_not_trigger_the_harness_warning():
    """Illegal moves are a result about the model. Warning on them would train
    a reader to discount exactly the failure the benchmark measures -- only
    unreadable replies implicate the parser."""
    episodes = [{"health": _health(accepted=300, rejected_illegal=200)}]
    assert action_health(episodes)[1] is None


def test_the_record_keeps_counts_and_rates_without_disturbing_the_sum():
    episodes = [
        {"health": _health(accepted=40, rejected_illegal=10)},
        {"health": _health(accepted=60, rejected_illegal=10)},
    ]
    assert health_totals(episodes)["accepted"] == 100
    stored = health_with_rates(episodes)
    assert stored["accepted"] == 100 and stored["rejected_illegal"] == 20
    assert stored["rates"]["illegal_rate"] == pytest.approx(0.1667, abs=1e-4)


def test_a_saved_run_can_be_re_aggregated_from_disk():
    """A record's health block carries the derived `rates` beside the counts.
    Comparing two published runs means summing those blocks again, and that
    must not choke on the value that is not a tally."""
    stored = health_with_rates([{"health": _health(accepted=40, rejected_illegal=10)}])
    assert "rates" in stored
    assert health_totals([{"health": stored}])["accepted"] == 40


def test_incomplete_episodes_are_marked_in_the_count():
    """A budget-stopped episode must not silently dilute a mean."""
    manifest = {"scoring": {"primary_metric": "dead_pct", "metrics": [
        {"name": "dead_pct", "type": "terminal_field", "field": "dead_pct"},
    ]}}
    episodes = [{"score": {"dead_pct": 10.0}}, {"score": {"outcome": None}}]
    assert "n=1" in dict(aggregate(manifest, episodes))["dead_pct"]


def test_system_prompt_carries_the_published_rules():
    import json
    from pathlib import Path
    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "benchanything.json").read_text(encoding="utf-8")
    )
    prompt = build_system_prompt(manifest, None)
    assert manifest["action_rules"][0] in prompt
    assert "victory_progress" in prompt
    assert "ACTION:" in prompt


def test_seeds_accept_names_and_integers():
    assert parse_seeds("USA, India, 42", 3) == ["USA", "India", 42]


def test_seed_list_extends_to_cover_the_episode_count():
    assert len(parse_seeds(None, 14)) == 14
