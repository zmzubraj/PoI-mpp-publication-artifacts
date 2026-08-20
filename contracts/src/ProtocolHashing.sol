// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library ProtocolHashing {
    bytes32 internal constant TASK_DOMAIN = bytes32("POI_MPP_TASK");
    bytes32 internal constant MODEL_DOMAIN = bytes32("POI_MPP_MODEL");
    bytes32 internal constant RESPONSE_COMMITMENT_DOMAIN = bytes32("POI_MPP_RESPONSE_COMMITMENT");
    uint16 internal constant DOMAIN_VERSION = 1;

    function taskCommitment(
        uint256 taskId,
        bytes32 taskRoot,
        address worker,
        uint8 taskClass,
        uint256 creditBudget,
        uint64 epoch,
        uint64 deadline
    ) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(TASK_DOMAIN, DOMAIN_VERSION, taskId, taskRoot, worker, taskClass, creditBudget, epoch, deadline)
        );
    }

    function modelCommitment(bytes32 modelRoot, bytes32 runtimeRoot, bytes32 modelManifestHash, uint8 assuranceClass)
        internal
        pure
        returns (bytes32)
    {
        return
            keccak256(
                abi.encode(MODEL_DOMAIN, DOMAIN_VERSION, modelRoot, runtimeRoot, modelManifestHash, assuranceClass)
            );
    }

    function responseCommitment(
        bytes32 taskCommitmentHash,
        bytes32 modelCommitmentHash,
        bytes32 responseHash,
        bytes32 traceRoot,
        bytes32 evidenceRoot,
        bytes32 artifactRoot,
        bytes32 nonce
    ) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(
                RESPONSE_COMMITMENT_DOMAIN,
                DOMAIN_VERSION,
                taskCommitmentHash,
                modelCommitmentHash,
                responseHash,
                traceRoot,
                evidenceRoot,
                artifactRoot,
                nonce
            )
        );
    }
}
