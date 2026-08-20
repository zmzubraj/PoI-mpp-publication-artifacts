// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract CommitmentHub {
    struct Commitment { address worker; bytes32 responseRoot; bytes32 traceRoot; bytes32 evidenceRoot; bytes32 artifactRoot; uint64 blockNumber; uint256 bond; }
    mapping(uint256 => Commitment) public commitments;
    event ResponseCommitted(uint256 indexed taskId, address indexed worker, bytes32 responseRoot, bytes32 traceRoot, bytes32 evidenceRoot, bytes32 artifactRoot);
    function commitResponse(uint256 taskId, bytes32 responseRoot, bytes32 traceRoot, bytes32 evidenceRoot, bytes32 artifactRoot) external payable {
        require(commitments[taskId].worker == address(0), "already committed");
        commitments[taskId] = Commitment(msg.sender, responseRoot, traceRoot, evidenceRoot, artifactRoot, uint64(block.number), msg.value);
        emit ResponseCommitted(taskId, msg.sender, responseRoot, traceRoot, evidenceRoot, artifactRoot);
    }
}
