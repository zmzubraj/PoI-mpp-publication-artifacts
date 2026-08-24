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
    bytes32 internal constant EXPECTED_TASK_ENVELOPE_V2_ROOT =
        0x5b37c42cc679b1d5c9f7dfb38729902bbfe9859269bba604d5dc809a267ebc48;

    function testCommitmentVectorsMatchExpectedConstants() public view {
        (bytes32 taskCommitment_, bytes32 modelCommitment_, bytes32 responseCommitment_) = witnessBaselineCommitment();
        assertEq(taskCommitment_, EXPECTED_TASK_COMMITMENT, "task commitment");
        assertEq(modelCommitment_, EXPECTED_MODEL_COMMITMENT, "model commitment");
        assertEq(responseCommitment_, EXPECTED_RESPONSE_COMMITMENT, "response commitment");
    }

    function testTaskEnvelopeV2CanonicalBytesMatchPythonRoot() public {
        bytes memory canonical = bytes(vm.readFile("test/fixtures/task_envelope_v2_canonical.txt"));
        assertTrue(canonical.length > 0 && canonical[canonical.length - 1] == 0x0a, "fixture newline");
        assembly ("memory-safe") {
            mstore(canonical, sub(mload(canonical), 1))
        }
        assertEq(sha256(canonical), EXPECTED_TASK_ENVELOPE_V2_ROOT, "TaskEnvelopeV2 taskRoot");
    }

    function testResponseCommitmentIgnoresEnvelopeHeights() public {
        (bytes32 taskCommitment_, bytes32 modelCommitment_, bytes32 responseCommitment_) =
            witnessHeightInvariantCommitment();
        assertEq(taskCommitment_, EXPECTED_TASK_COMMITMENT, "height-invariant task commitment");
        assertEq(modelCommitment_, EXPECTED_MODEL_COMMITMENT, "height-invariant model commitment");
        assertEq(responseCommitment_, EXPECTED_RESPONSE_COMMITMENT, "height-invariant response commitment");
    }

    function testStateVectorActivationMatchesExpectedOrdinalAndEpoch() public {
        (uint8 stateOrdinal, uint64 activatedEpoch) = witnessStateActivateSuccess();
        assertEq(uint256(stateOrdinal), 2, "active ordinal");
        assertEq(activatedEpoch, 2, "activated epoch");
    }

    function testStateVectorPrematureActivationRevertsWithExpectedSelector() public {
        assertEq(
            uint256(uint32(witnessStatePrematureActivationRevert())),
            uint256(uint32(ReceiptManager.ReceiptManager__ActivationNotReady.selector)),
            "premature activation selector"
        );
    }

    function testStateVectorLateActivationRevertsWithExpectedSelector() public {
        assertEq(
            uint256(uint32(witnessStateLateActivationRevert())),
            uint256(uint32(ReceiptManager.ReceiptManager__ActivationWindowClosed.selector)),
            "late activation selector"
        );
    }

    function testCreditVectorSingleReceiptConsumesFullBudget() public {
        (
            uint256 firstShare,
            uint256 secondShare,
            uint256 allocated,
            uint256 epochCredit,
            uint256 activeWeight,
            bool consumed
        ) = witnessCreditSingleReceipt();
        assertEq(firstShare, 100, "receipt share");
        assertEq(secondShare, 0, "unused second share");
        assertEq(allocated, 100, "allocated");
        assertEq(epochCredit, 100, "epoch raw credit");
        assertEq(activeWeight, 100, "active weight");
        assertTrue(consumed, "receipt consumed");
    }

    function testCreditVectorTwoReceiptSplitIsDeterministic() public {
        (uint256 firstShare, uint256 secondShare, uint256 allocated, uint256 epochCredit) =
            witnessCreditTwoReceiptSplit();
        assertEq(firstShare, 50, "first share");
        assertEq(secondShare, 50, "second share");
        assertEq(allocated, 100, "allocated");
        assertEq(epochCredit, 100, "epoch raw credit");
    }

    function testCreditVectorServiceTaskIsDeterministicNoOp() public {
        (uint256 allocated, uint256 receiptCredit, uint256 epochCredit, bool consumed) = witnessCreditServiceTaskNoOp();
        assertEq(allocated, 0, "service allocation remains zero");
        assertEq(receiptCredit, 0, "service receipt credit remains zero");
        assertEq(epochCredit, 0, "service raw credit remains zero");
        assertTrue(!consumed, "service task does not consume receipt");
    }

    function testCreditVectorZeroBudgetTaskIsDeterministicNoOp() public {
        (uint256 allocated, uint256 receiptCredit, uint256 epochCredit, bool consumed) = witnessCreditZeroBudgetNoOp();
        assertEq(allocated, 0, "zero-budget allocation remains zero");
        assertEq(receiptCredit, 0, "zero-budget receipt credit remains zero");
        assertEq(epochCredit, 0, "zero-budget raw credit remains zero");
        assertTrue(!consumed, "zero-budget task does not consume receipt");
    }

    function testCreditVectorInactiveTaskIsDeterministicNoOp() public {
        (uint256 allocated, uint256 receiptCredit, uint256 epochCredit, bool consumed) = witnessCreditInactiveTaskNoOp();
        assertEq(allocated, 0, "inactive allocation remains zero");
        assertEq(receiptCredit, 0, "inactive receipt credit remains zero");
        assertEq(epochCredit, 0, "inactive raw credit remains zero");
        assertTrue(!consumed, "inactive task does not consume receipt");
    }

    function testCreditVectorEmptyBatchFailsClosed() public {
        assertEq(
            uint256(uint32(witnessCreditEmptyBatchRevert())),
            uint256(uint32(CreditEngine.CreditEngine__NoActiveReceipt.selector)),
            "empty batch selector"
        );
    }

    function testCreditVectorWrongEpochRejected() public {
        assertEq(
            uint256(uint32(witnessCreditWrongEpochRevert())),
            uint256(uint32(CreditEngine.CreditEngine__ReceiptWrongEpoch.selector)),
            "wrong epoch selector"
        );
    }

    function testCreditVectorRejectsDuplicateReceiptBatch() public {
        assertEq(
            uint256(uint32(witnessCreditDuplicateReceiptBatchRevert())),
            uint256(uint32(CreditEngine.CreditEngine__ReceiptIdsNotStrictlyAscending.selector)),
            "duplicate batch selector"
        );
    }

    function testCreditVectorReplayRejected() public {
        assertEq(
            uint256(uint32(witnessCreditReplayRevert())),
            uint256(uint32(CreditEngine.CreditEngine__ReceiptAlreadyCredited.selector)),
            "replay selector"
        );
    }

    function witnessBaselineCommitment() public view returns (bytes32, bytes32, bytes32) {
        CommitmentHub.Commitment memory committed = commitmentHub.getCommitment(consensusTaskId);
        return (
            taskManager.taskCommitment(consensusTaskId),
            modelRegistry.modelCommitment(MODEL_ROOT),
            committed.commitmentHash
        );
    }

    function witnessHeightInvariantCommitment() public returns (bytes32, bytes32, bytes32) {
        bytes32 beforeRoll = commitmentHub.previewResponseCommitment(
            consensusTaskId, RESPONSE_ROOT, TRACE_ROOT, EVIDENCE_ROOT, ARTIFACT_ROOT, NONCE
        );
        vm.roll(block.number + 100);
        bytes32 afterRoll = commitmentHub.previewResponseCommitment(
            consensusTaskId, RESPONSE_ROOT, TRACE_ROOT, EVIDENCE_ROOT, ARTIFACT_ROOT, NONCE
        );
        assertEq(beforeRoll, afterRoll, "preview commitment must ignore block height");
        return (taskManager.taskCommitment(consensusTaskId), modelRegistry.modelCommitment(MODEL_ROOT), afterRoll);
    }

    function witnessStateActivateSuccess() public returns (uint8, uint64) {
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);
        ReceiptManager.Receipt memory receipt = receiptManager.getReceipt(pendingReceiptId);
        return (uint8(receipt.state), receipt.activatedEpoch);
    }

    function witnessStatePrematureActivationRevert() public returns (bytes4) {
        vm.prank(RECEIPT_OPERATOR);
        try receiptManager.activate(pendingReceiptId) {
            revert("expected activation revert");
        } catch (bytes memory reason) {
            return bytes4(reason);
        }
    }

    function witnessStateLateActivationRevert() public returns (bytes4) {
        AuditManager.AuditRound memory round = auditManager.getAudit(consensusTaskId);
        vm.roll(uint256(round.challengeDeadline) + BLOCKS_PER_EPOCH + 1);
        vm.prank(RECEIPT_OPERATOR);
        try receiptManager.activate(pendingReceiptId) {
            revert("expected late activation revert");
        } catch (bytes memory reason) {
            return bytes4(reason);
        }
    }

    function witnessCreditSingleReceipt() public returns (uint256, uint256, uint256, uint256, uint256, bool) {
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);

        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);

        vm.prank(CREDIT_OPERATOR);
        creditEngine.setCollateral(WORKER, 1_000);

        return (
            creditEngine.receiptCredit(pendingReceiptId),
            0,
            creditEngine.taskAllocated(consensusTaskId),
            creditEngine.rawCredit(2, WORKER),
            creditEngine.activeWeight(2, WORKER),
            creditEngine.creditedReceipts(pendingReceiptId)
        );
    }

    function witnessCreditTwoReceiptSplit() public returns (uint256, uint256, uint256, uint256) {
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

        return (
            creditEngine.receiptCredit(pendingReceiptId),
            creditEngine.receiptCredit(secondReceiptId),
            creditEngine.taskAllocated(consensusTaskId),
            creditEngine.rawCredit(2, WORKER)
        );
    }

    function witnessCreditServiceTaskNoOp() public returns (uint256, uint256, uint256, bool) {
        uint256 serviceReceiptId =
            _prepareTaskWithActiveReceipt(serviceTaskId, ALT_WORKER, keccak256("service-vector-nullifier"));
        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = serviceReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(serviceTaskId, receiptIds);

        return (
            creditEngine.taskAllocated(serviceTaskId),
            creditEngine.receiptCredit(serviceReceiptId),
            creditEngine.rawCredit(2, ALT_WORKER),
            creditEngine.creditedReceipts(serviceReceiptId)
        );
    }

    function witnessCreditZeroBudgetNoOp() public returns (uint256, uint256, uint256, bool) {
        uint256 zeroBudgetTaskId =
            _createTask(keccak256("zero-budget-task-root"), WORKER, TaskManager.TaskClass.CONSENSUS, 0);
        uint256 zeroBudgetReceiptId =
            _prepareTaskWithActiveReceipt(zeroBudgetTaskId, WORKER, keccak256("zero-budget-nullifier"));
        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = zeroBudgetReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(zeroBudgetTaskId, receiptIds);

        return (
            creditEngine.taskAllocated(zeroBudgetTaskId),
            creditEngine.receiptCredit(zeroBudgetReceiptId),
            creditEngine.rawCredit(2, WORKER),
            creditEngine.creditedReceipts(zeroBudgetReceiptId)
        );
    }

    function witnessCreditInactiveTaskNoOp() public returns (uint256, uint256, uint256, bool) {
        uint256 inactiveTaskId =
            _createTask(keccak256("inactive-task-root"), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        uint256 inactiveReceiptId =
            _prepareTaskWithActiveReceipt(inactiveTaskId, WORKER, keccak256("inactive-nullifier"));
        _setTaskActive(inactiveTaskId, false);
        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = inactiveReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(inactiveTaskId, receiptIds);

        return (
            creditEngine.taskAllocated(inactiveTaskId),
            creditEngine.receiptCredit(inactiveReceiptId),
            creditEngine.rawCredit(2, WORKER),
            creditEngine.creditedReceipts(inactiveReceiptId)
        );
    }

    function witnessCreditEmptyBatchRevert() public returns (bytes4) {
        uint256[] memory receiptIds = new uint256[](0);
        vm.prank(CREDIT_OPERATOR);
        try creditEngine.allocateCredit(consensusTaskId, receiptIds) {
            revert("expected empty batch revert");
        } catch (bytes memory reason) {
            return bytes4(reason);
        }
    }

    function witnessCreditWrongEpochRevert() public returns (bytes4) {
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);
        _setTaskEpoch(consensusTaskId, 2);

        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        try creditEngine.allocateCredit(consensusTaskId, receiptIds) {
            revert("expected wrong epoch revert");
        } catch (bytes memory reason) {
            return bytes4(reason);
        }
    }

    function witnessCreditDuplicateReceiptBatchRevert() public returns (bytes4) {
        uint256 secondReceiptId = _mintPendingReceipt(keccak256("vector-duplicate-nullifier"));
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);
        _activatePendingReceipt(secondReceiptId);

        uint256[] memory duplicateBatch = new uint256[](2);
        duplicateBatch[0] = pendingReceiptId;
        duplicateBatch[1] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        try creditEngine.allocateCredit(consensusTaskId, duplicateBatch) {
            revert("expected duplicate batch revert");
        } catch (bytes memory reason) {
            return bytes4(reason);
        }
    }

    function witnessCreditReplayRevert() public returns (bytes4) {
        _matureReceiptWindow(consensusTaskId);
        vm.roll(block.number + 1);
        _activatePendingReceipt(pendingReceiptId);

        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = pendingReceiptId;

        vm.prank(CREDIT_OPERATOR);
        creditEngine.allocateCredit(consensusTaskId, receiptIds);

        vm.prank(CREDIT_OPERATOR);
        try creditEngine.allocateCredit(consensusTaskId, receiptIds) {
            revert("expected replay revert");
        } catch (bytes memory reason) {
            return bytes4(reason);
        }
    }
}
