// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../test/HashVectors.t.sol";

interface VmJson {
    function projectRoot() external view returns (string memory);
    function toString(bytes32 value) external pure returns (string memory);
    function toString(uint256 value) external pure returns (string memory);
    function writeJson(string calldata json, string calldata path) external;
    function roll(uint256 newHeight) external;
}

contract ProtocolVectorWitness {
    VmJson internal constant vmJson = VmJson(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external {
        string memory path = string.concat(vmJson.projectRoot(), "/out/protocol_witnesses.json");

        HashVectors baseline = _newFixture();
        (bytes32 baselineTask, bytes32 baselineModel, bytes32 baselineResponse) = baseline.witnessBaselineCommitment();

        HashVectors heightInvariant = _newFixture();
        (bytes32 lateTask, bytes32 lateModel, bytes32 lateResponse) = heightInvariant.witnessHeightInvariantCommitment();

        HashVectors activateSuccess = _newFixture();
        (uint8 stateOrdinal, uint64 activatedEpoch) = activateSuccess.witnessStateActivateSuccess();

        HashVectors premature = _newFixture();
        bytes4 prematureSelector = premature.witnessStatePrematureActivationRevert();

        HashVectors late = _newFixture();
        bytes4 lateSelector = late.witnessStateLateActivationRevert();

        HashVectors singleCredit = _newFixture();
        (
            uint256 singleFirst,
            uint256 singleSecond,
            uint256 singleAllocated,
            uint256 singleEpochCredit,
            uint256 singleWeight,
            bool singleConsumed
        ) = singleCredit.witnessCreditSingleReceipt();

        HashVectors splitCredit = _newFixture();
        (uint256 splitFirst, uint256 splitSecond, uint256 splitAllocated, uint256 splitEpochCredit) =
            splitCredit.witnessCreditTwoReceiptSplit();

        HashVectors serviceNoOp = _newFixture();
        (uint256 serviceAllocated, uint256 serviceReceiptCredit, uint256 serviceEpochCredit, bool serviceConsumed) =
            serviceNoOp.witnessCreditServiceTaskNoOp();

        HashVectors zeroBudget = _newFixture();
        (uint256 zeroAllocated, uint256 zeroReceiptCredit, uint256 zeroEpochCredit, bool zeroConsumed) =
            zeroBudget.witnessCreditZeroBudgetNoOp();

        HashVectors inactiveNoOp = _newFixture();
        (uint256 inactiveAllocated, uint256 inactiveReceiptCredit, uint256 inactiveEpochCredit, bool inactiveConsumed) =
            inactiveNoOp.witnessCreditInactiveTaskNoOp();

        HashVectors emptyBatch = _newFixture();
        bytes4 emptyBatchSelector = emptyBatch.witnessCreditEmptyBatchRevert();

        HashVectors wrongEpoch = _newFixture();
        bytes4 wrongEpochSelector = wrongEpoch.witnessCreditWrongEpochRevert();

        HashVectors duplicateBatch = _newFixture();
        bytes4 duplicateBatchSelector = duplicateBatch.witnessCreditDuplicateReceiptBatchRevert();

        HashVectors replay = _newFixture();
        bytes4 replaySelector = replay.witnessCreditReplayRevert();

        string memory json = string.concat(
            "{",
            "\"schema\":\"POI_MPP_SOLIDITY_WITNESSES_V1\",",
            "\"commitment\":{",
            "\"baseline\":",
            _commitmentJson(baselineTask, baselineModel, baselineResponse),
            ",",
            "\"height_invariant\":",
            _commitmentJson(lateTask, lateModel, lateResponse),
            "},",
            "\"state\":{",
            "\"activate_success\":",
            _activateSuccessJson(stateOrdinal, activatedEpoch),
            ",",
            "\"premature_activation_revert\":\"",
            _selectorString(prematureSelector),
            "\",",
            "\"late_activation_revert\":\"",
            _selectorString(lateSelector),
            "\"",
            "},",
            "\"credit\":{",
            "\"single_receipt_budget\":",
            _singleCreditJson(
                singleFirst, singleSecond, singleAllocated, singleEpochCredit, singleWeight, singleConsumed
            ),
            ",",
            "\"two_receipt_even_split\":",
            _twoCreditJson(splitFirst, splitSecond, splitAllocated, splitEpochCredit),
            ",",
            "\"service_task_noop\":",
            _noopCreditJson(serviceAllocated, serviceReceiptCredit, serviceEpochCredit, serviceConsumed),
            ",",
            "\"zero_budget_noop\":",
            _noopCreditJson(zeroAllocated, zeroReceiptCredit, zeroEpochCredit, zeroConsumed),
            ",",
            "\"inactive_task_noop\":",
            _noopCreditJson(inactiveAllocated, inactiveReceiptCredit, inactiveEpochCredit, inactiveConsumed),
            ",",
            "\"empty_batch_revert\":\"",
            _selectorString(emptyBatchSelector),
            "\",",
            "\"wrong_epoch_revert\":\"",
            _selectorString(wrongEpochSelector),
            "\",",
            "\"duplicate_receipt_batch_revert\":\"",
            _selectorString(duplicateBatchSelector),
            "\",",
            "\"replay_revert\":\"",
            _selectorString(replaySelector),
            "\"",
            "}",
            "}"
        );

        vmJson.writeJson(json, path);
    }

    function _newFixture() private returns (HashVectors fixture) {
        vmJson.roll(1);
        fixture = new HashVectors();
        fixture.setUp();
    }

    function _commitmentJson(bytes32 taskCommitment_, bytes32 modelCommitment_, bytes32 commitmentHash_)
        private
        view
        returns (string memory)
    {
        return string.concat(
            "{",
            "\"task_commitment\":\"",
            vmJson.toString(taskCommitment_),
            "\",",
            "\"model_commitment\":\"",
            vmJson.toString(modelCommitment_),
            "\",",
            "\"commitment_hash\":\"",
            vmJson.toString(commitmentHash_),
            "\"",
            "}"
        );
    }

    function _activateSuccessJson(uint8 stateOrdinal, uint64 activatedEpoch) private view returns (string memory) {
        return string.concat(
            "{",
            "\"state\":",
            vmJson.toString(uint256(stateOrdinal)),
            ",",
            "\"activated_epoch\":",
            vmJson.toString(uint256(activatedEpoch)),
            "}"
        );
    }

    function _singleCreditJson(
        uint256 firstShare,
        uint256 secondShare,
        uint256 allocated,
        uint256 epochCredit,
        uint256 activeWeight,
        bool consumed
    ) private view returns (string memory) {
        return string.concat(
            "{",
            "\"receipt_1\":",
            vmJson.toString(firstShare),
            ",",
            "\"receipt_2\":",
            vmJson.toString(secondShare),
            ",",
            "\"allocated\":",
            vmJson.toString(allocated),
            ",",
            "\"epoch_credit\":",
            vmJson.toString(epochCredit),
            ",",
            "\"active_weight\":",
            vmJson.toString(activeWeight),
            ",",
            "\"consumed\":",
            _jsonBool(consumed),
            "}"
        );
    }

    function _twoCreditJson(uint256 firstShare, uint256 secondShare, uint256 allocated, uint256 epochCredit)
        private
        view
        returns (string memory)
    {
        return string.concat(
            "{",
            "\"receipt_1\":",
            vmJson.toString(firstShare),
            ",",
            "\"receipt_2\":",
            vmJson.toString(secondShare),
            ",",
            "\"allocated\":",
            vmJson.toString(allocated),
            ",",
            "\"epoch_credit\":",
            vmJson.toString(epochCredit),
            "}"
        );
    }

    function _noopCreditJson(uint256 allocated, uint256 receiptCredit, uint256 epochCredit, bool consumed)
        private
        view
        returns (string memory)
    {
        return string.concat(
            "{",
            "\"allocated\":",
            vmJson.toString(allocated),
            ",",
            "\"receipt_credit\":",
            vmJson.toString(receiptCredit),
            ",",
            "\"epoch_credit\":",
            vmJson.toString(epochCredit),
            ",",
            "\"consumed\":",
            _jsonBool(consumed),
            "}"
        );
    }

    function _selectorString(bytes4 selector) private view returns (string memory) {
        return vmJson.toString(bytes32(selector));
    }

    function _jsonBool(bool value) private pure returns (string memory) {
        return value ? "true" : "false";
    }
}
