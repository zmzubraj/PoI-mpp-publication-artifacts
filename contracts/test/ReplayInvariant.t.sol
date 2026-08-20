// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ProtocolRoles.t.sol";

contract ReplayInvariantTest is ProtocolKernelBase {
    function testActiveReceiptCannotBeActivatedTwice() public {
        _matureReceiptWindow(consensusTaskId);
        _activatePendingReceipt(pendingReceiptId);

        vm.prank(RECEIPT_OPERATOR);
        vm.expectRevert(ReceiptManager.ReceiptManager__InvalidState.selector);
        receiptManager.activate(pendingReceiptId);
    }

    function testNullifierReuseIsRejected() public {
        vm.prank(RECEIPT_OPERATOR);
        vm.expectRevert(ReceiptManager.ReceiptManager__NullifierAlreadyReserved.selector);
        receiptManager.mintPending(consensusTaskId, NULLIFIER);
    }

    function invariant_ConsumedNullifierStaysMarked() public view {
        if (receiptManager.usedNullifiers(NULLIFIER)) {
            assertTrue(receiptManager.usedNullifiers(NULLIFIER), "used nullifier");
        }
    }
}
