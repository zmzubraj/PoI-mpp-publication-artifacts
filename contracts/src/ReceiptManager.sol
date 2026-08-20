// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./PolicyRegistry.sol";
import "./TaskManager.sol";
import "./CommitmentHub.sol";
import "./AuditManager.sol";

contract ReceiptManager {
    error ReceiptManager__ActivationNotReady();
    error ReceiptManager__AuditMissing();
    error ReceiptManager__ChallengeNotConfirmed();
    error ReceiptManager__InvalidNullifier();
    error ReceiptManager__InvalidState();
    error ReceiptManager__NullifierAlreadyReserved();
    error ReceiptManager__NullifierAlreadyUsed();
    error ReceiptManager__SlashNotConfirmed();
    error ReceiptManager__Unauthorized();

    uint16 public constant EVENT_VERSION = 1;

    enum State {
        NONE,
        PENDING,
        ACTIVE,
        ABSTAINED,
        CHALLENGED,
        DA_FAILED,
        EXPIRED,
        REJECTED,
        SLASHED
    }

    PolicyRegistry public immutable policy;
    TaskManager public immutable taskManager;
    CommitmentHub public immutable commitmentHub;
    AuditManager public immutable auditManager;

    struct Receipt {
        uint256 taskId;
        address worker;
        bytes32 commitmentHash;
        bytes32 auditId;
        bytes32 nullifier;
        State state;
        uint64 epochIssued;
        uint64 challengeDeadline;
        uint64 activatedEpoch;
    }

    uint256 public nextReceiptId = 1;
    mapping(uint256 => Receipt) public receipts;

    mapping(bytes32 => bool) public reservedNullifiers;
    mapping(bytes32 => bool) public usedNullifiers;
    mapping(uint256 => mapping(address => uint256)) public activeReceiptCount;

    event ReceiptMintedV1(
        uint16 indexed version,
        uint256 indexed receiptId,
        uint256 indexed taskId,
        address worker,
        bytes32 commitmentHash,
        bytes32 auditId,
        bytes32 nullifier
    );
    event ReceiptActivatedV1(
        uint16 indexed version,
        uint256 indexed receiptId,
        uint256 indexed taskId,
        address worker,
        bytes32 nullifier,
        uint64 activatedEpoch
    );
    event ReceiptChallengedV1(uint16 indexed version, uint256 indexed receiptId);
    event ReceiptSlashedV1(uint16 indexed version, uint256 indexed receiptId);

    constructor(address policy_, address taskManager_, address commitmentHub_, address auditManager_) {
        policy = PolicyRegistry(policy_);
        taskManager = TaskManager(taskManager_);
        commitmentHub = CommitmentHub(commitmentHub_);
        auditManager = AuditManager(auditManager_);
    }

    modifier onlyReceiptOperator() {
        if (!policy.hasRole(policy.RECEIPT_OPERATOR_ROLE(), msg.sender)) {
            revert ReceiptManager__Unauthorized();
        }
        _;
    }

    function mintPending(uint256 taskId, bytes32 nullifier) external onlyReceiptOperator returns (uint256 id) {
        if (nullifier == bytes32(0)) {
            revert ReceiptManager__InvalidNullifier();
        }
        if (reservedNullifiers[nullifier]) {
            revert ReceiptManager__NullifierAlreadyReserved();
        }

        TaskManager.Task memory task = taskManager.getTask(taskId);
        CommitmentHub.Commitment memory committed = commitmentHub.getCommitment(taskId);
        AuditManager.AuditRound memory round = auditManager.getAudit(taskId);
        if (!task.active || !task.registered || !committed.exists || !round.exists) {
            revert ReceiptManager__AuditMissing();
        }

        id = nextReceiptId++;
        reservedNullifiers[nullifier] = true;
        receipts[id] = Receipt(
            taskId,
            task.worker,
            committed.commitmentHash,
            round.auditId,
            nullifier,
            State.PENDING,
            task.epoch,
            round.challengeDeadline,
            0
        );
        emit ReceiptMintedV1(EVENT_VERSION, id, taskId, task.worker, committed.commitmentHash, round.auditId, nullifier);
    }

    function activate(uint256 receiptId) external onlyReceiptOperator {
        Receipt storage receipt = receipts[receiptId];
        if (receipt.state != State.PENDING) {
            revert ReceiptManager__InvalidState();
        }
        if (usedNullifiers[receipt.nullifier]) {
            revert ReceiptManager__NullifierAlreadyUsed();
        }
        if (
            block.number <= receipt.epochIssued || block.number != receipt.challengeDeadline
                || !auditManager.isReceiptActivatable(receipt.taskId)
        ) {
            revert ReceiptManager__ActivationNotReady();
        }

        usedNullifiers[receipt.nullifier] = true;
        receipt.state = State.ACTIVE;
        receipt.activatedEpoch = receipt.epochIssued + 1;
        activeReceiptCount[receipt.taskId][receipt.worker] += 1;
        emit ReceiptActivatedV1(
            EVENT_VERSION, receiptId, receipt.taskId, receipt.worker, receipt.nullifier, receipt.activatedEpoch
        );
    }

    function markChallenged(uint256 receiptId) external onlyReceiptOperator {
        Receipt storage receipt = receipts[receiptId];
        if (receipt.state != State.PENDING) {
            revert ReceiptManager__InvalidState();
        }
        if (!auditManager.isTaskChallenged(receipt.taskId)) {
            revert ReceiptManager__ChallengeNotConfirmed();
        }
        receipt.state = State.CHALLENGED;
        emit ReceiptChallengedV1(EVENT_VERSION, receiptId);
    }

    function slash(uint256 receiptId) external onlyReceiptOperator {
        Receipt storage receipt = receipts[receiptId];
        if (receipt.state != State.CHALLENGED) {
            revert ReceiptManager__InvalidState();
        }
        if (!auditManager.isTaskSlashed(receipt.taskId)) {
            revert ReceiptManager__SlashNotConfirmed();
        }
        receipt.state = State.SLASHED;
        emit ReceiptSlashedV1(EVENT_VERSION, receiptId);
    }

    function isActiveReceipt(uint256 receiptId) external view returns (bool) {
        return receipts[receiptId].state == State.ACTIVE;
    }

    function getReceipt(uint256 receiptId) external view returns (Receipt memory) {
        return receipts[receiptId];
    }
}
