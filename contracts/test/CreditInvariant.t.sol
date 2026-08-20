// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ProtocolRoles.t.sol";

contract CreditInvariantTest is ProtocolKernelBase {
    function testServiceTaskCannotMintConsensusCredit() public {
        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__TaskNotCreditable.selector);
        creditEngine.addCredit(serviceTaskId, pendingReceiptId, ALT_WORKER, 1);
    }

    function testZeroCreditProducesZeroWeight() public {
        vm.prank(CREDIT_OPERATOR);
        creditEngine.setCollateral(WORKER, 1_000);
        assertEq(creditEngine.activeWeight(2, WORKER), 0, "zero credit weight");
    }

    function testFuzz_TaskAllocationNeverExceedsBudget(uint96 firstCredit, uint96 secondCredit) public {
        uint256 secondReceiptId = _mintPendingReceipt(keccak256("budget-second-receipt"));
        _matureReceiptWindow(consensusTaskId);
        _activatePendingReceipt(pendingReceiptId);
        _activatePendingReceipt(secondReceiptId);

        TaskManager.Task memory task = taskManager.getTask(consensusTaskId);
        vm.assume(firstCredit <= task.creditBudget);

        vm.prank(CREDIT_OPERATOR);
        creditEngine.addCredit(consensusTaskId, pendingReceiptId, WORKER, firstCredit);

        uint256 remaining = task.creditBudget - firstCredit;
        if (secondCredit > remaining) {
            vm.prank(CREDIT_OPERATOR);
            vm.expectRevert(CreditEngine.CreditEngine__BudgetExceeded.selector);
            creditEngine.addCredit(consensusTaskId, secondReceiptId, WORKER, secondCredit);
        } else {
            vm.prank(CREDIT_OPERATOR);
            creditEngine.addCredit(consensusTaskId, secondReceiptId, WORKER, secondCredit);
            assertEq(
                creditEngine.taskAllocated(consensusTaskId), uint256(firstCredit) + uint256(secondCredit), "allocated"
            );
        }
    }

    function testCreditRequiresSpecificActiveReceiptAndPreventsReplay() public {
        _matureReceiptWindow(consensusTaskId);
        _activatePendingReceipt(pendingReceiptId);

        vm.prank(CREDIT_OPERATOR);
        creditEngine.addCredit(consensusTaskId, pendingReceiptId, WORKER, 10);

        assertEq(creditEngine.taskAllocated(consensusTaskId), 10, "task credit");
        assertEq(creditEngine.rawCredit(2, WORKER), 10, "epoch credit");

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__ReceiptAlreadyCredited.selector);
        creditEngine.addCredit(consensusTaskId, pendingReceiptId, WORKER, 1);
    }

    function testInactiveOrMismatchedReceiptCannotMintCredit() public {
        uint256 otherReceiptId = _mintPendingReceipt(keccak256("other-nullifier"));

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__ReceiptNotActive.selector);
        creditEngine.addCredit(consensusTaskId, otherReceiptId, WORKER, 1);

        _matureReceiptWindow(consensusTaskId);
        _activatePendingReceipt(pendingReceiptId);

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__TaskNotCreditable.selector);
        creditEngine.addCredit(serviceTaskId, pendingReceiptId, WORKER, 1);

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__WorkerMismatch.selector);
        creditEngine.addCredit(consensusTaskId, pendingReceiptId, ALT_WORKER, 1);
    }

    function invariant_TaskAllocationNeverExceedsBudget() public view {
        TaskManager.Task memory task = taskManager.getTask(consensusTaskId);
        assertTrue(creditEngine.taskAllocated(consensusTaskId) <= task.creditBudget, "budget");
    }
}
