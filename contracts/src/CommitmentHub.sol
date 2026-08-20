// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ModelRegistry.sol";
import "./PolicyRegistry.sol";
import "./ProtocolHashing.sol";
import "./TaskManager.sol";

contract CommitmentHub {
    error CommitmentHub__AlreadyCommitted();
    error CommitmentHub__CommitmentMissing();
    error CommitmentHub__InvalidRoot();
    error CommitmentHub__TaskInactive();
    error CommitmentHub__WorkerMismatch();

    uint16 public constant EVENT_VERSION = 1;

    PolicyRegistry public immutable policy;
    TaskManager public immutable taskManager;

    struct Commitment {
        uint256 taskId;
        address worker;
        bytes32 taskCommitment;
        bytes32 modelCommitment;
        bytes32 commitmentHash;
        bytes32 responseHash;
        bytes32 traceRoot;
        bytes32 evidenceRoot;
        bytes32 artifactRoot;
        bytes32 nonce;
        uint64 committedBlock;
        uint64 finalizedBlock;
        bool exists;
    }

    mapping(uint256 => Commitment) public commitments;

    event ResponseCommittedV1(
        uint16 indexed version,
        uint256 indexed taskId,
        address indexed worker,
        bytes32 taskCommitment,
        bytes32 modelCommitment,
        bytes32 commitmentHash,
        bytes32 responseHash,
        bytes32 traceRoot,
        bytes32 evidenceRoot,
        bytes32 artifactRoot,
        bytes32 nonce,
        uint64 committedBlock,
        uint64 finalizedBlock
    );

    constructor(address policy_, address taskManager_) {
        policy = PolicyRegistry(policy_);
        taskManager = TaskManager(taskManager_);
    }

    function commitResponse(
        uint256 taskId,
        bytes32 responseHash,
        bytes32 traceRoot,
        bytes32 evidenceRoot,
        bytes32 artifactRoot,
        bytes32 nonce
    ) external payable {
        if (
            responseHash == bytes32(0) || traceRoot == bytes32(0) || evidenceRoot == bytes32(0)
                || artifactRoot == bytes32(0)
        ) {
            revert CommitmentHub__InvalidRoot();
        }

        TaskManager.Task memory task = taskManager.getTask(taskId);
        if (!task.active || !task.registered) {
            revert CommitmentHub__TaskInactive();
        }
        if (task.worker != msg.sender || !taskManager.isRegisteredWorker(msg.sender)) {
            revert CommitmentHub__WorkerMismatch();
        }
        if (commitments[taskId].exists) {
            revert CommitmentHub__AlreadyCommitted();
        }

        Commitment storage committed = commitments[taskId];
        committed.taskId = taskId;
        committed.worker = msg.sender;
        committed.taskCommitment = taskManager.taskCommitment(taskId);
        committed.modelCommitment = ModelRegistry(address(taskManager.modelRegistry())).modelCommitment(task.modelRoot);
        committed.responseHash = responseHash;
        committed.traceRoot = traceRoot;
        committed.evidenceRoot = evidenceRoot;
        committed.artifactRoot = artifactRoot;
        committed.nonce = nonce;
        committed.committedBlock = uint64(block.number);
        committed.finalizedBlock = committed.committedBlock + policy.commitmentFinalityDepth();
        committed.commitmentHash = ProtocolHashing.responseCommitment(
            committed.taskCommitment,
            committed.modelCommitment,
            committed.responseHash,
            committed.traceRoot,
            committed.evidenceRoot,
            committed.artifactRoot,
            committed.nonce
        );
        committed.exists = true;

        emit ResponseCommittedV1(
            EVENT_VERSION,
            taskId,
            msg.sender,
            committed.taskCommitment,
            committed.modelCommitment,
            committed.commitmentHash,
            committed.responseHash,
            committed.traceRoot,
            committed.evidenceRoot,
            committed.artifactRoot,
            committed.nonce,
            committed.committedBlock,
            committed.finalizedBlock
        );
    }

    function previewResponseCommitment(
        uint256 taskId,
        bytes32 responseHash,
        bytes32 traceRoot,
        bytes32 evidenceRoot,
        bytes32 artifactRoot,
        bytes32 nonce
    ) external view returns (bytes32) {
        TaskManager.Task memory task = taskManager.getTask(taskId);
        bytes32 taskCommitmentHash = taskManager.taskCommitment(taskId);
        bytes32 modelCommitmentHash =
            ModelRegistry(address(taskManager.modelRegistry())).modelCommitment(task.modelRoot);
        return ProtocolHashing.responseCommitment(
            taskCommitmentHash, modelCommitmentHash, responseHash, traceRoot, evidenceRoot, artifactRoot, nonce
        );
    }

    function isFinalized(uint256 taskId) external view returns (bool) {
        Commitment memory committed = commitments[taskId];
        return committed.exists && block.number >= committed.finalizedBlock;
    }

    function getCommitment(uint256 taskId) external view returns (Commitment memory) {
        Commitment memory committed = commitments[taskId];
        if (!committed.exists) {
            revert CommitmentHub__CommitmentMissing();
        }
        return committed;
    }
}
