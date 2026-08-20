// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ProtocolRoles.t.sol";

contract ReceiptLifecycleTest is ProtocolKernelBase {
    function testReceiptCannotActivateBeforeAuditDaAndWindow() public {
        vm.prank(RECEIPT_OPERATOR);
        vm.expectRevert(ReceiptManager.ReceiptManager__ActivationNotReady.selector);
        receiptManager.activate(pendingReceiptId);
    }

    function testReceiptActivatesOnlyAfterAllGates() public {
        _matureReceiptWindow(consensusTaskId);

        vm.prank(RECEIPT_OPERATOR);
        receiptManager.activate(pendingReceiptId);

        ReceiptManager.Receipt memory receipt = receiptManager.getReceipt(pendingReceiptId);
        assertEq(uint256(uint8(receipt.state)), uint256(uint8(ReceiptManager.State.ACTIVE)), "state");
        assertTrue(receiptManager.usedNullifiers(NULLIFIER), "nullifier should be consumed");
    }

    function testSuccessfulChallengeSlashesReceipt() public {
        vm.prank(RECEIPT_OPERATOR);
        uint256 challengedReceiptId = receiptManager.mintPending(consensusTaskId, keccak256("challenge-nullifier"));

        vm.prank(AUDITOR);
        auditManager.openChallenge(consensusTaskId, keccak256("dispute-root"));

        vm.prank(RECEIPT_OPERATOR);
        receiptManager.markChallenged(challengedReceiptId);

        vm.prank(AUDITOR);
        auditManager.slash(consensusTaskId);

        vm.prank(RECEIPT_OPERATOR);
        receiptManager.slash(challengedReceiptId);

        ReceiptManager.Receipt memory receipt = receiptManager.getReceipt(challengedReceiptId);
        assertEq(uint256(uint8(receipt.state)), uint256(uint8(ReceiptManager.State.SLASHED)), "slashed");
    }
}
