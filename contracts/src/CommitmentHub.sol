// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./PolicyRegistry.sol";
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
        bytes32 commitmentHash;
        bytes32 responseRoot;
        bytes32 traceRoot;
        bytes32 evidenceRoot;
        bytes32 artifactRoot;
        uint64 committedBlock;
        uint64 finalizedBlock;
        bool exists;
    }

    mapping(uint256 => Commitment) public commitments;

    event ResponseCommittedV1(
        uint16 indexed version,
        uint256 indexed taskId,
        address indexed worker,
        bytes32 commitmentHash,
        bytes32 responseRoot,
        bytes32 traceRoot,
        bytes32 evidenceRoot,
        bytes32 artifactRoot,
        uint64 committedBlock,
        uint64 finalizedBlock
    );

    constructor(address policy_, address taskManager_) {
        policy = PolicyRegistry(policy_);
        taskManager = TaskManager(taskManager_);
    }

    function commitResponse(
        uint256 taskId,
        bytes32 responseRoot,
        bytes32 traceRoot,
        bytes32 evidenceRoot,
        bytes32 artifactRoot
    ) external payable {
        if (
            responseRoot == bytes32(0) || traceRoot == bytes32(0) || evidenceRoot == bytes32(0)
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

        uint64 committedBlock = uint64(block.number);
        uint64 finalizedBlock = committedBlock + policy.commitmentFinalityDepth();
        bytes32 commitmentHash = keccak256(
            abi.encode(
                EVENT_VERSION,
                taskId,
                msg.sender,
                responseRoot,
                traceRoot,
                evidenceRoot,
                artifactRoot,
                committedBlock,
                finalizedBlock
            )
        );

        commitments[taskId] = Commitment(
            taskId,
            msg.sender,
            commitmentHash,
            responseRoot,
            traceRoot,
            evidenceRoot,
            artifactRoot,
            committedBlock,
            finalizedBlock,
            true
        );

        emit ResponseCommittedV1(
            EVENT_VERSION,
            taskId,
            msg.sender,
            commitmentHash,
            responseRoot,
            traceRoot,
            evidenceRoot,
            artifactRoot,
            committedBlock,
            finalizedBlock
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
