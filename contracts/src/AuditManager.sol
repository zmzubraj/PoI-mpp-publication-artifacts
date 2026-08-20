// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./PolicyRegistry.sol";
import "./CommitmentHub.sol";

contract AuditManager {
    error AuditManager__AlreadyOpened();
    error AuditManager__AlreadyRecorded();
    error AuditManager__AuditMissing();
    error AuditManager__ChallengeClosed();
    error AuditManager__CommitmentNotFinalized();
    error AuditManager__InvalidDecision();
    error AuditManager__NotChallengeable();
    error AuditManager__Unauthorized();

    uint16 public constant EVENT_VERSION = 1;

    enum AuditDecision {
        NONE,
        ACCEPT,
        REJECT,
        ABSTAIN
    }

    PolicyRegistry public immutable policy;
    CommitmentHub public immutable commitmentHub;

    struct AuditRound {
        bytes32 auditId;
        bytes32 commitmentHash;
        bytes32 seedHash;
        bytes32 policyHash;
        uint32 roundIndex;
        uint64 openedBlock;
        uint64 challengeDeadline;
        AuditDecision decision;
        bool daPassed;
        bool daRecorded;
        bool challenged;
        bool slashed;
        bool exists;
    }

    mapping(uint256 => AuditRound) public rounds;

    event AuditOpenedV1(
        uint16 indexed version,
        uint256 indexed taskId,
        bytes32 indexed auditId,
        bytes32 commitmentHash,
        bytes32 seedHash,
        bytes32 policyHash,
        uint32 roundIndex,
        uint64 openedBlock,
        uint64 challengeDeadline
    );
    event AuditDecisionRecordedV1(uint16 indexed version, uint256 indexed taskId, AuditDecision decision);
    event DataAvailabilityRecordedV1(uint16 indexed version, uint256 indexed taskId, bool available);
    event ChallengeOpenedV1(uint16 indexed version, uint256 indexed taskId, bytes32 indexed disputeRoot);
    event ReceiptSlashedV1(uint16 indexed version, uint256 indexed taskId);

    constructor(address policy_, address commitmentHub_) {
        policy = PolicyRegistry(policy_);
        commitmentHub = CommitmentHub(commitmentHub_);
    }

    modifier onlyAuditor() {
        if (!policy.hasRole(policy.AUDITOR_ROLE(), msg.sender)) {
            revert AuditManager__Unauthorized();
        }
        _;
    }

    function openAudit(uint256 taskId, bytes32 auditId, bytes32 seedHash, bytes32 policyHash, uint32 roundIndex)
        external
        onlyAuditor
    {
        if (rounds[taskId].exists) {
            revert AuditManager__AlreadyOpened();
        }
        if (!commitmentHub.isFinalized(taskId)) {
            revert AuditManager__CommitmentNotFinalized();
        }
        CommitmentHub.Commitment memory committed = commitmentHub.getCommitment(taskId);
        uint64 challengeDeadline = uint64(block.number) + policy.challengeWindowBlocks();
        rounds[taskId] = AuditRound(
            auditId,
            committed.commitmentHash,
            seedHash,
            policyHash,
            roundIndex,
            uint64(block.number),
            challengeDeadline,
            AuditDecision.NONE,
            false,
            false,
            false,
            false,
            true
        );
        emit AuditOpenedV1(
            EVENT_VERSION,
            taskId,
            auditId,
            committed.commitmentHash,
            seedHash,
            policyHash,
            roundIndex,
            uint64(block.number),
            challengeDeadline
        );
    }

    function recordAuditResult(uint256 taskId, AuditDecision decision) external onlyAuditor {
        AuditRound storage round = rounds[taskId];
        if (!round.exists) {
            revert AuditManager__AuditMissing();
        }
        if (round.decision != AuditDecision.NONE) {
            revert AuditManager__AlreadyRecorded();
        }
        if (decision == AuditDecision.NONE) {
            revert AuditManager__InvalidDecision();
        }
        round.decision = decision;
        emit AuditDecisionRecordedV1(EVENT_VERSION, taskId, decision);
    }

    function recordDataAvailability(uint256 taskId, bool available) external onlyAuditor {
        AuditRound storage round = rounds[taskId];
        if (!round.exists) {
            revert AuditManager__AuditMissing();
        }
        if (round.daRecorded) {
            revert AuditManager__AlreadyRecorded();
        }
        round.daRecorded = true;
        round.daPassed = available;
        emit DataAvailabilityRecordedV1(EVENT_VERSION, taskId, available);
    }

    function openChallenge(uint256 taskId, bytes32 disputeRoot) external onlyAuditor {
        AuditRound storage round = rounds[taskId];
        if (!round.exists) {
            revert AuditManager__AuditMissing();
        }
        if (round.decision != AuditDecision.ACCEPT || !round.daRecorded || !round.daPassed || round.slashed) {
            revert AuditManager__NotChallengeable();
        }
        if (block.number > round.challengeDeadline) {
            revert AuditManager__ChallengeClosed();
        }
        round.challenged = true;
        emit ChallengeOpenedV1(EVENT_VERSION, taskId, disputeRoot);
    }

    function slash(uint256 taskId) external onlyAuditor {
        AuditRound storage round = rounds[taskId];
        if (!round.exists) {
            revert AuditManager__AuditMissing();
        }
        if (!round.challenged || round.slashed) {
            revert AuditManager__NotChallengeable();
        }
        round.slashed = true;
        emit ReceiptSlashedV1(EVENT_VERSION, taskId);
    }

    function isTaskChallenged(uint256 taskId) external view returns (bool) {
        AuditRound memory round = rounds[taskId];
        return round.exists && round.challenged;
    }

    function isTaskSlashed(uint256 taskId) external view returns (bool) {
        AuditRound memory round = rounds[taskId];
        return round.exists && round.slashed;
    }

    function isReceiptActivatable(uint256 taskId) external view returns (bool) {
        AuditRound memory round = rounds[taskId];
        return round.exists && round.decision == AuditDecision.ACCEPT && round.daRecorded && round.daPassed
            && !round.challenged && !round.slashed && block.number >= round.challengeDeadline;
    }

    function getAudit(uint256 taskId) external view returns (AuditRound memory) {
        AuditRound memory round = rounds[taskId];
        if (!round.exists) {
            revert AuditManager__AuditMissing();
        }
        return round;
    }
}
