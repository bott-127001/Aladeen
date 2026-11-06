"""Focused, isolated replay regression suite for ActivationEngine.

Provides separately retrievable verification of:
- Canonical length-prefixed identifier encodings with adversarial delimiters
- Full multi-generation lifecycle execution (touches, external commit, departure, rearm, invalidations)
- Bit-for-bit snapshot equality across every intermediate replay prefix
- Bit-for-bit canonical full-state checkpoint equality across every prefix:
  (processed events, observation associations, member consumed observations,
   generation counters, current members, active activations, terminal activations,
   rearm controllers, sequence, and coverage)
- Invoking-engine immutability: calling replay() on an active engine leaves it completely unmutated.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from aladeen.strategy.activation_engine import ActivationEngine, ActivationEngineConfig
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CancellationReason,
    ExactPricePrint,
    ExternalCommitEvent,
    PriceBasis,
    RegisterMembersEvent,
    SequenceDomain,
    SourceCancellationEvent,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_activation_id,
    format_member_key,
)
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction


@pytest.fixture
def default_domain() -> SequenceDomain:
    return SequenceDomain("FEED_EURUSD_H1", "RUN_TEST_01")


class TestActivationReplayExecution:
    """Full lifecycle adversarial-delimiter replay regression suite."""

    def test_canonical_unambiguous_identifiers_with_adversarial_delimiters_and_every_prefix_replay(
        self, default_domain: SequenceDomain
    ) -> None:
        """Exercises full lifecycle with adversarial delimiters and asserts every-prefix snapshot and checkpoint equality."""
        # 1. Component encoding checks: length-prefixing guarantees collision-free encoding
        id1 = format_activation_id("a::H4", "H1", "x", "SET", "TJL1", 1)
        id2 = format_activation_id("a", "H4", "H1::x", "SET", "TJL1", 1)
        assert id1 != id2
        assert id1 == "ACT_G01[5:a::H4][2:H1][1:x][3:SET][4:TJL1]"
        assert id2 == "ACT_G01[1:a][2:H4][5:H1::x][3:SET][4:TJL1]"

        mk1 = format_member_key("SET::1", "TJL1")
        mk2 = format_member_key("SET", "1::TJL1")
        assert mk1 != mk2
        assert mk1 == "MK[6:SET::1][4:TJL1]"
        assert mk2 == "MK[3:SET][7:1::TJL1]"

        # 2. Live engine full lifecycle execution with recorded events
        config = ActivationEngineConfig("ENGINE::EURUSD::H1", "FEED::EURUSD::H1", "H1", default_domain, PriceBasis.BID)
        eng = ActivationEngine(config)
        lvl = StableLevelId("FEED::EURUSD::H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m_adv1 = SourceMemberReference(
            "ENGINE::EURUSD::H1", "FEED::EURUSD::H1", "H1", "SET::1", "TJL1", "HIGH",
            1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            UsageEvidenceStatus.UNUSED
        )
        m_adv2 = SourceMemberReference(
            "ENGINE::EURUSD::H1", "FEED::EURUSD::H1", "H1", "SET", "TJL1", "HIGH",
            1.1040, 1.1050, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            UsageEvidenceStatus.UNUSED
        )

        ev_reg = RegisterMembersEvent("EV_REG", default_domain, 100, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), (m_adv1, m_adv2))
        ev_touch1 = ExactPricePrint("O1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 101)
        ev_touch2 = ExactPricePrint("O2", 1.1045, PriceBasis.BID, datetime(2026, 10, 2, 8, 20, tzinfo=timezone.utc), default_domain, 102)
        ev_commit = ExternalCommitEvent("C1", datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), default_domain, 103, winning_engine_id="OTHER", winning_set_id="OTHER_SET", winning_role="TJL1")
        ev_dep = ExactPricePrint("O_DEP", 1.1200, PriceBasis.BID, datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc), default_domain, 104)
        ev_ret1 = ExactPricePrint("O_RET1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 40, tzinfo=timezone.utc), default_domain, 105)
        ev_ret2 = ExactPricePrint("O_RET2", 1.1045, PriceBasis.BID, datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), default_domain, 106)
        ev_cancel_set1 = SourceCancellationEvent("CAN_SET1", CancellationReason.SOURCE_REPLACEMENT, default_domain, 107, datetime(2026, 10, 2, 8, 50, tzinfo=timezone.utc), target_set_id="SET::1")
        ev_choch = SourceCancellationEvent("CAN_CHOCH", CancellationReason.SOURCE_CHOCH, default_domain, 108, datetime(2026, 10, 2, 8, 55, tzinfo=timezone.utc), affected_direction=Direction.UPWARD)

        recorded_events = [ev_reg, ev_touch1, ev_touch2, ev_commit, ev_dep, ev_ret1, ev_ret2, ev_cancel_set1, ev_choch]
        seq_snapshots = []
        seq_checkpoints = []

        # Process sequentially on eng, recording snapshot and full internal checkpoint after each event:
        snap_reg = eng.process_event(ev_reg)
        seq_snapshots.append(snap_reg)
        seq_checkpoints.append(eng.create_checkpoint())
        assert len(snap_reg.current_members) == 2
        assert m_adv1.member_key != m_adv2.member_key

        # Phase A: First activation touches for both adversarial members
        snap_touch1 = eng.process_event(ev_touch1)
        seq_snapshots.append(snap_touch1)
        seq_checkpoints.append(eng.create_checkpoint())

        snap_act = eng.process_event(ev_touch2)
        seq_snapshots.append(snap_act)
        seq_checkpoints.append(eng.create_checkpoint())

        act1 = snap_act.active_activations[m_adv1.member_key]
        act2 = snap_act.active_activations[m_adv2.member_key]
        assert act1.state == ActivationState.PENDING_ACTIVATION
        assert act2.state == ActivationState.PENDING_ACTIVATION
        assert act1.activation_id != act2.activation_id
        assert act1.activation_id == format_activation_id("ENGINE::EURUSD::H1", "H1", "FEED::EURUSD::H1", "SET::1", "TJL1", 1)
        assert act2.activation_id == format_activation_id("ENGINE::EURUSD::H1", "H1", "FEED::EURUSD::H1", "SET", "TJL1", 1)

        # Phase B: External cancellation terminalizes both into CANCELLED_EXTERNAL_ENTRY
        snap_commit = eng.process_event(ev_commit)
        seq_snapshots.append(snap_commit)
        seq_checkpoints.append(eng.create_checkpoint())
        assert len(snap_commit.active_activations) == 0
        assert len(snap_commit.terminal_activations) == 2
        assert len(snap_commit.rearm_controllers) == 2
        assert snap_commit.rearm_controllers[m_adv1.member_key].prior_activation_id == act1.activation_id
        assert snap_commit.rearm_controllers[m_adv2.member_key].prior_activation_id == act2.activation_id

        # Phase C: Confirmed departure outside both zones
        snap_dep = eng.process_event(ev_dep)
        seq_snapshots.append(snap_dep)
        seq_checkpoints.append(eng.create_checkpoint())
        assert snap_dep.rearm_controllers[m_adv1.member_key].state == ActivationState.OUT_OF_ZONE_ARMED
        assert snap_dep.rearm_controllers[m_adv2.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        # Phase D: Linked reactivation touches creating generation 2
        snap_ret1 = eng.process_event(ev_ret1)
        seq_snapshots.append(snap_ret1)
        seq_checkpoints.append(eng.create_checkpoint())

        snap_rearm = eng.process_event(ev_ret2)
        seq_snapshots.append(snap_rearm)
        seq_checkpoints.append(eng.create_checkpoint())

        react1 = snap_rearm.active_activations[m_adv1.member_key]
        react2 = snap_rearm.active_activations[m_adv2.member_key]
        assert react1.state == ActivationState.REARMED_PENDING
        assert react2.state == ActivationState.REARMED_PENDING
        assert react1.generation_seq == 2
        assert react2.generation_seq == 2
        assert react1.activation_id != react2.activation_id
        assert react1.prior_activation_id == act1.activation_id
        assert react2.prior_activation_id == act2.activation_id

        # Phase E: Source invalidation targeted specifically at SET::1 (does not affect SET)
        snap_after_cancel1 = eng.process_event(ev_cancel_set1)
        seq_snapshots.append(snap_after_cancel1)
        seq_checkpoints.append(eng.create_checkpoint())
        assert m_adv1.member_key not in snap_after_cancel1.current_members
        assert m_adv2.member_key in snap_after_cancel1.current_members
        assert m_adv2.member_key in snap_after_cancel1.active_activations

        # Source CHOCH invalidates remaining SET
        snap_final = eng.process_event(ev_choch)
        seq_snapshots.append(snap_final)
        seq_checkpoints.append(eng.create_checkpoint())
        assert len(snap_final.current_members) == 0
        assert len(snap_final.active_activations) == 0
        assert len(snap_final.terminal_activations) == 4
        # All 4 terminal activations have globally unique IDs
        terminal_ids = [t.activation_id for t in snap_final.terminal_activations]
        assert len(terminal_ids) == len(set(terminal_ids))

        # Capture invoking engine state prior to replay calls
        pre_replay_snapshot = eng.get_snapshot()
        pre_replay_checkpoint = eng.create_checkpoint()

        # Phase F: Every-prefix replay equivalence from scratch across snapshots and full checkpoint state
        assert len(seq_snapshots) == len(recorded_events)
        assert len(seq_checkpoints) == len(recorded_events)

        # Replay full event sequence via .replay() API
        replay_engine = ActivationEngine(config)
        replayed_snapshots = replay_engine.replay(recorded_events)
        assert len(replayed_snapshots) == len(seq_snapshots)

        # Assert every intermediate prefix snapshot and full-state checkpoint bit-for-bit equivalence
        for prefix_len in range(1, len(recorded_events) + 1):
            # 1. Verify .replay() returned prefix snapshot matches sequential snapshot
            assert replayed_snapshots[prefix_len - 1] == seq_snapshots[prefix_len - 1]

            # 2. Replay prefix on an isolated engine and verify full future-behavior checkpoint state:
            # processed events, observation associations, consumed observations, generation counts,
            # active/terminal activations, rearm controllers, sequence, and coverage
            prefix_engine = ActivationEngine(config)
            for ev in recorded_events[:prefix_len]:
                prefix_engine.process_event(ev)
            assert prefix_engine.get_snapshot() == seq_snapshots[prefix_len - 1]
            assert prefix_engine.create_checkpoint() == seq_checkpoints[prefix_len - 1]

        # Phase G: Verify calling replay on invoking engine does not mutate the invoking engine
        isolated_snaps = eng.replay(recorded_events[:3])
        assert len(isolated_snaps) == 3
        assert eng.get_snapshot() == pre_replay_snapshot
        assert eng.create_checkpoint() == pre_replay_checkpoint
