// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ProtocolRoles.t.sol";

contract CreditInvariantTest is ProtocolKernelBase {
    function testServiceTaskCannotMintConsensusCredit() public {
        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = pendingReceiptId;
        uint256 beforeAllocated = creditEngine.taskAllocated(serviceTaskId);
        uint256 beforeReceiptCredit = creditEngine.receiptCredit(pendingReceiptId);
        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(serviceTaskId, receiptIds);
        assertEq(creditEngine.taskAllocated(serviceTaskId), beforeAllocated, "service task allocation");
        assertEq(creditEngine.receiptCredit(pendingReceiptId), beforeReceiptCredit, "service task receipt credit");
    }

    function testZeroCreditProducesZeroWeight() public {
        vm.prank(CREDIT_OPERATOR);
        creditEngine.setCollateral(WORKER, 1_000);
        assertEq(creditEngine.activeWeight(2, WORKER), 0, "zero credit weight");
    }

    function testTaskAllocationConsumesExactBudgetAcrossCanonicalReceiptBatch() public {
        uint256 secondReceiptId = _mintPendingReceipt(keccak256("budget-second-receipt"));
        _matureReceiptWindow(consensusTaskId);
        _activatePendingReceipt(pendingReceiptId);
        _activatePendingReceipt(secondReceiptId);

        uint256[] memory receiptIds = new uint256[](2);
        receiptIds[0] = pendingReceiptId;
        receiptIds[1] = secondReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);

        TaskManager.Task memory task = taskManager.getTask(consensusTaskId);
        assertEq(creditEngine.taskAllocated(consensusTaskId), task.creditBudget, "allocated");
        assertEq(creditEngine.rawCredit(2, WORKER), task.creditBudget, "epoch credit");
    }

    function testCreditRequiresCanonicalActiveReceiptBatchAndPreventsReplay() public {
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);

        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);

        assertEq(creditEngine.taskAllocated(consensusTaskId), 100, "task credit");
        assertEq(creditEngine.rawCredit(2, WORKER), 100, "epoch credit");

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__ReceiptAlreadyCredited.selector);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);
    }

    function testInactiveOrMismatchedReceiptCannotMintCredit() public {
        uint256 otherReceiptId = _mintPendingReceipt(keccak256("other-nullifier"));
        uint256[] memory singleReceipt = new uint256[](1);
        singleReceipt[0] = otherReceiptId;

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__NoActiveReceipt.selector);
        creditEngine.allocateCredit(consensusTaskId, singleReceipt);

        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(serviceTaskId, singleReceipt);
        assertEq(creditEngine.taskAllocated(serviceTaskId), 0, "service task remains zero");

        singleReceipt[0] = pendingReceiptId;
        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(serviceTaskId, singleReceipt);
        assertEq(creditEngine.receiptCredit(pendingReceiptId), 0, "service task cannot consume receipt");
    }

    function testReceiptBatchMustCoverAllActiveReceipts() public {
        uint256 secondReceiptId = _mintPendingReceipt(keccak256("coverage-second-receipt"));
        _matureReceiptWindow(consensusTaskId);
        _activatePendingReceipt(pendingReceiptId);
        _activatePendingReceipt(secondReceiptId);

        uint256[] memory subset = new uint256[](1);
        subset[0] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__ActiveReceiptCountMismatch.selector);
        creditEngine.allocateCredit(consensusTaskId, subset);
    }

    function testCreditableConsensusTaskWithEmptyBatchFailsClosed() public {
        uint256[] memory receiptIds = new uint256[](0);
        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__NoActiveReceipt.selector);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);
    }

    function invariant_TaskAllocationNeverExceedsBudget() public view {
        TaskManager.Task memory task = taskManager.getTask(consensusTaskId);
        assertTrue(creditEngine.taskAllocated(consensusTaskId) <= task.creditBudget, "budget");
    }
}
