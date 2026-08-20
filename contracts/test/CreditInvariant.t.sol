// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ProtocolRoles.t.sol";

contract CreditInvariantTest is ProtocolKernelBase {
    function testServiceTaskCannotMintConsensusCredit() public {
        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__TaskNotCreditable.selector);
        creditEngine.addCredit(serviceTaskId, ALT_WORKER, 1);
    }

    function testZeroCreditProducesZeroWeight() public {
        vm.prank(CREDIT_OPERATOR);
        creditEngine.setCollateral(WORKER, 1_000);
        assertEq(creditEngine.activeWeight(2, WORKER), 0, "zero credit weight");
    }

    function testFuzz_TaskAllocationNeverExceedsBudget(uint96 firstCredit, uint96 secondCredit) public {
        _matureReceiptWindow(consensusTaskId);
        _activatePendingReceipt(pendingReceiptId);

        TaskManager.Task memory task = taskManager.getTask(consensusTaskId);
        vm.assume(firstCredit <= task.creditBudget);

        vm.prank(CREDIT_OPERATOR);
        creditEngine.addCredit(consensusTaskId, WORKER, firstCredit);

        uint256 remaining = task.creditBudget - firstCredit;
        if (secondCredit > remaining) {
            vm.prank(CREDIT_OPERATOR);
            vm.expectRevert(CreditEngine.CreditEngine__BudgetExceeded.selector);
            creditEngine.addCredit(consensusTaskId, WORKER, secondCredit);
        } else {
            vm.prank(CREDIT_OPERATOR);
            creditEngine.addCredit(consensusTaskId, WORKER, secondCredit);
            assertEq(
                creditEngine.taskAllocated(consensusTaskId), uint256(firstCredit) + uint256(secondCredit), "allocated"
            );
        }
    }

    function invariant_TaskAllocationNeverExceedsBudget() public view {
        TaskManager.Task memory task = taskManager.getTask(consensusTaskId);
        assertTrue(creditEngine.taskAllocated(consensusTaskId) <= task.creditBudget, "budget");
    }
}
