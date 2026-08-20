// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ProtocolRoles.t.sol";

contract HashVectors is ProtocolKernelBase {
    bytes32 internal constant EXPECTED_TASK_COMMITMENT =
        0xa71131195fdcd5e87b0cf127d654805ac004377e439897e7f626a052221f07d2;
    bytes32 internal constant EXPECTED_MODEL_COMMITMENT =
        0x6cc38e7d8ed382ce80d3142fef6db5d65f77e5e7c13bed9b732212ad35c3f55f;
    bytes32 internal constant EXPECTED_RESPONSE_COMMITMENT =
        0xcd90bb210febc07e2db63ffaa2297d921e3c520e52ccf525df89d089dd3ed66b;

    function testCommitmentVectorsMatchExpectedConstants() public view {
        CommitmentHub.Commitment memory committed = commitmentHub.getCommitment(consensusTaskId);
        assertEq(taskManager.taskCommitment(consensusTaskId), EXPECTED_TASK_COMMITMENT, "task commitment");
        assertEq(modelRegistry.modelCommitment(MODEL_ROOT), EXPECTED_MODEL_COMMITMENT, "model commitment");
        assertEq(committed.taskCommitment, EXPECTED_TASK_COMMITMENT, "stored task commitment");
        assertEq(committed.modelCommitment, EXPECTED_MODEL_COMMITMENT, "stored model commitment");
        assertEq(committed.commitmentHash, EXPECTED_RESPONSE_COMMITMENT, "response commitment");
    }

    function testResponseCommitmentIgnoresEnvelopeHeights() public {
        bytes32 beforeRoll = commitmentHub.previewResponseCommitment(
            consensusTaskId, RESPONSE_ROOT, TRACE_ROOT, EVIDENCE_ROOT, ARTIFACT_ROOT, NONCE
        );
        vm.roll(block.number + 100);
        bytes32 afterRoll = commitmentHub.previewResponseCommitment(
            consensusTaskId, RESPONSE_ROOT, TRACE_ROOT, EVIDENCE_ROOT, ARTIFACT_ROOT, NONCE
        );
        assertEq(beforeRoll, EXPECTED_RESPONSE_COMMITMENT, "preview commitment");
        assertEq(afterRoll, EXPECTED_RESPONSE_COMMITMENT, "preview should ignore block height");
    }

    function testStateVectorActivationMatchesExpectedOrdinalAndEpoch() public {
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);

        vm.prank(RECEIPT_OPERATOR);
        receiptManager.activate(pendingReceiptId);

        ReceiptManager.Receipt memory receipt = receiptManager.getReceipt(pendingReceiptId);
        assertEq(uint256(uint8(receipt.state)), 2, "active ordinal");
        assertEq(receipt.activatedEpoch, 2, "activated epoch");
    }

    function testStateVectorPrematureActivationRevertsWithExpectedSelector() public {
        vm.prank(RECEIPT_OPERATOR);
        vm.expectRevert(ReceiptManager.ReceiptManager__ActivationNotReady.selector);
        receiptManager.activate(pendingReceiptId);
    }

    function testStateVectorLateActivationRevertsWithExpectedSelector() public {
        AuditManager.AuditRound memory round = auditManager.getAudit(consensusTaskId);
        vm.roll(uint256(round.challengeDeadline) + BLOCKS_PER_EPOCH + 1);

        vm.prank(RECEIPT_OPERATOR);
        vm.expectRevert(ReceiptManager.ReceiptManager__ActivationWindowClosed.selector);
        receiptManager.activate(pendingReceiptId);
    }

    function testCreditVectorSingleReceiptConsumesFullBudget() public {
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);

        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);

        vm.prank(CREDIT_OPERATOR);
        creditEngine.setCollateral(WORKER, 1_000);

        assertEq(creditEngine.receiptCredit(pendingReceiptId), 100, "receipt share");
        assertEq(creditEngine.taskAllocated(consensusTaskId), 100, "allocated");
        assertEq(creditEngine.rawCredit(2, WORKER), 100, "epoch raw credit");
        assertEq(creditEngine.activeWeight(2, WORKER), 100, "active weight");
    }

    function testCreditVectorTwoReceiptSplitIsDeterministic() public {
        uint256 secondReceiptId = _mintPendingReceipt(keccak256("vector-second-nullifier"));
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);
        _activatePendingReceipt(secondReceiptId);

        uint256[] memory receiptIds = new uint256[](2);
        receiptIds[0] = pendingReceiptId;
        receiptIds[1] = secondReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);

        assertEq(creditEngine.receiptCredit(pendingReceiptId), 50, "first share");
        assertEq(creditEngine.receiptCredit(secondReceiptId), 50, "second share");
        assertEq(creditEngine.taskAllocated(consensusTaskId), 100, "allocated");
        assertEq(creditEngine.rawCredit(2, WORKER), 100, "epoch raw credit");
    }

    function testCreditVectorRejectsNonAscendingReceiptBatch() public {
        uint256 secondReceiptId = _mintPendingReceipt(keccak256("vector-third-nullifier"));
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);
        _activatePendingReceipt(secondReceiptId);

        uint256[] memory descending = new uint256[](2);
        descending[0] = secondReceiptId;
        descending[1] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        vm.expectRevert(CreditEngine.CreditEngine__ReceiptIdsNotStrictlyAscending.selector);
        creditEngine.allocateCredit(consensusTaskId, descending);
    }
}
