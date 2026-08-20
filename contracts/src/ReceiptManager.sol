// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract ReceiptManager {
    enum State { NONE, PENDING, ACTIVE, EXPIRED, SLASHED }
    struct Receipt { uint256 taskId; address worker; bytes32 commitmentRoot; uint16 scoreBps; uint8 assuranceClass; State state; uint64 epoch; }
    uint256 public nextReceiptId = 1;
    mapping(uint256 => Receipt) public receipts;
    event ReceiptMinted(uint256 indexed receiptId, uint256 indexed taskId, address worker);
    event ReceiptActivated(uint256 indexed receiptId);
    function mintPending(uint256 taskId, address worker, bytes32 commitmentRoot, uint16 scoreBps, uint8 assuranceClass, uint64 epoch) external returns (uint256 id) {
        id = nextReceiptId++;
        receipts[id] = Receipt(taskId, worker, commitmentRoot, scoreBps, assuranceClass, State.PENDING, epoch);
        emit ReceiptMinted(id, taskId, worker);
    }
    function activate(uint256 receiptId) external {
        require(receipts[receiptId].state == State.PENDING, "state");
        receipts[receiptId].state = State.ACTIVE;
        emit ReceiptActivated(receiptId);
    }
}
