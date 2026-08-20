// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract AuditManager {
    struct AuditRound { bytes32 seed; uint64 openedAt; bool challenged; bool resolved; }
    mapping(uint256 => AuditRound) public rounds;
    event AuditOpened(uint256 indexed taskId, bytes32 seed);
    event Challenged(uint256 indexed taskId, bytes32 disputeRoot);
    function openAudit(uint256 taskId, bytes32 seed) external { rounds[taskId] = AuditRound(seed, uint64(block.number), false, false); emit AuditOpened(taskId, seed); }
    function challenge(uint256 taskId, bytes32 disputeRoot) external payable { rounds[taskId].challenged = true; emit Challenged(taskId, disputeRoot); }
}
