// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ProtocolRoles.t.sol";

interface VmJson is Vm {
    function projectRoot() external view returns (string memory);
    function toString(uint256 value) external pure returns (string memory);
    function writeJson(string calldata json, string calldata path) external;
}

contract GasSnapshots is ProtocolKernelBase {
    bytes32 internal constant EXTRA_MODEL_ROOT = keccak256("extra-model-root");
    bytes32 internal constant EXTRA_RUNTIME_ROOT = keccak256("extra-runtime-root");
    bytes32 internal constant EXTRA_MANIFEST_HASH = keccak256("extra-model-manifest");

    VmJson internal constant vmJson = VmJson(address(uint160(uint256(keccak256("hevm cheat code")))));

    function testGasModelRegister() public {
        witnessModelRegister();
    }

    function testGasTaskCreate() public {
        witnessTaskCreate();
    }

    function testGasCommitResponse() public {
        witnessCommitResponse();
    }

    function testGasAuditOpen() public {
        witnessAuditOpen();
    }

    function testGasAuditRecordResult() public {
        witnessAuditRecordResult();
    }

    function testGasAuditRecordDa() public {
        witnessAuditRecordDa();
    }

    function testGasOpenChallenge() public {
        witnessOpenChallenge();
    }

    function testGasReceiptMintPending() public {
        witnessReceiptMintPending();
    }

    function testGasReceiptActivate() public {
        witnessReceiptActivate();
    }

    function testGasReceiptMarkChallenged() public {
        witnessReceiptMarkChallenged();
    }

    function testGasReceiptSlash() public {
        witnessReceiptSlash();
    }

    function testGasCreditAllocateBatch1() public {
        witnessCreditAllocate(1);
    }

    function testGasCreditAllocateBatch2() public {
        witnessCreditAllocate(2);
    }

    function testGasCreditAllocateBatch4() public {
        witnessCreditAllocate(4);
    }

    function testGasCreditAllocateBatch8() public {
        witnessCreditAllocate(8);
    }

    function witnessModelRegister()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        bytes32[] memory slots = new bytes32[](4);
        bytes32 base = _mappingSlot(EXTRA_MODEL_ROOT, 0);
        for (uint256 index = 0; index < 4; index++) {
            slots[index] = bytes32(uint256(base) + index);
        }
        vm.prank(MODEL_ADMIN);
        uint256 gasBefore = gasleft();
        modelRegistry.registerModel(EXTRA_MODEL_ROOT, EXTRA_RUNTIME_ROOT, EXTRA_MANIFEST_HASH, 2);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        changedStorageSlotCount = _countChangedSlots(address(modelRegistry), baseline.modelRegistryAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessTaskCreate()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        uint256 taskId = serviceTaskId + 1;
        uint64 currentEpoch = policy.currentEpoch();
        bytes32 base = _mappingSlot(taskId, 1);
        bytes32[] memory slots = new bytes32[](6);
        slots[0] = bytes32(uint256(0));
        for (uint256 index = 0; index < 5; index++) {
            slots[index + 1] = bytes32(uint256(base) + index);
        }
        vm.prank(TASK_ADMIN);
        uint256 gasBefore = gasleft();
        taskManager.createTask(
            keccak256("gas-task-create"),
            MODEL_ROOT,
            WORKER,
            TaskManager.TaskClass.CONSENSUS,
            120,
            currentEpoch,
            600
        );
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        changedStorageSlotCount = _countChangedSlots(address(taskManager), baseline.taskManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessCommitResponse()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        uint256 taskId = prepareCommitResponseState();
        bytes32 base = _mappingSlot(taskId, 0);
        bytes32[] memory slots = new bytes32[](11);
        for (uint256 index = 0; index < 11; index++) {
            slots[index] = bytes32(uint256(base) + index);
        }
        vm.prank(WORKER);
        uint256 gasBefore = gasleft();
        commitmentHub.commitResponse(taskId, RESPONSE_ROOT, TRACE_ROOT, EVIDENCE_ROOT, ARTIFACT_ROOT, NONCE);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareCommitResponseState();
        changedStorageSlotCount = _countChangedSlots(address(commitmentHub), baseline.commitmentHubAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessAuditOpen()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        uint256 taskId = prepareAuditOpenState();
        bytes32[] memory slots = _auditSlots(taskId);
        vm.prank(AUDITOR);
        uint256 gasBefore = gasleft();
        auditManager.openAudit(taskId, keccak256("gas-audit-id"), SEED_HASH, POLICY_HASH, 0);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareAuditOpenState();
        changedStorageSlotCount = _countChangedSlots(address(auditManager), baseline.auditManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessAuditRecordResult()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        uint256 taskId = prepareOpenedAuditState(keccak256("gas-audit-result"));
        bytes32[] memory slots = new bytes32[](1);
        slots[0] = bytes32(uint256(_mappingSlot(taskId, 0)) + 4);
        vm.prank(AUDITOR);
        uint256 gasBefore = gasleft();
        auditManager.recordAuditResult(taskId, AuditManager.AuditDecision.ACCEPT);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareOpenedAuditState(keccak256("gas-audit-result"));
        changedStorageSlotCount = _countChangedSlots(address(auditManager), baseline.auditManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessAuditRecordDa()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        uint256 taskId = prepareOpenedAuditState(keccak256("gas-audit-da"));
        bytes32[] memory slots = new bytes32[](1);
        slots[0] = bytes32(uint256(_mappingSlot(taskId, 0)) + 4);
        vm.prank(AUDITOR);
        uint256 gasBefore = gasleft();
        auditManager.recordDataAvailability(taskId, true);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareOpenedAuditState(keccak256("gas-audit-da"));
        changedStorageSlotCount = _countChangedSlots(address(auditManager), baseline.auditManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessOpenChallenge()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        bytes32[] memory slots = new bytes32[](1);
        slots[0] = bytes32(uint256(_mappingSlot(consensusTaskId, 0)) + 4);
        vm.prank(AUDITOR);
        uint256 gasBefore = gasleft();
        auditManager.openChallenge(consensusTaskId, keccak256("gas-dispute-root"));
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        changedStorageSlotCount = _countChangedSlots(address(auditManager), baseline.auditManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessReceiptMintPending()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        uint256 taskId = prepareReceiptMintPendingState();
        uint256 receiptId = pendingReceiptId + 1;
        bytes32 nullifier = keccak256("gas-receipt-nullifier");
        bytes32[] memory slots = _receiptMintSlots(receiptId, nullifier);
        vm.prank(RECEIPT_OPERATOR);
        uint256 gasBefore = gasleft();
        receiptManager.mintPending(taskId, nullifier);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareReceiptMintPendingState();
        changedStorageSlotCount = _countChangedSlots(address(receiptManager), baseline.receiptManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessReceiptActivate()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        prepareReceiptActivateState();
        bytes32[] memory slots = _receiptActivateSlots(pendingReceiptId, consensusTaskId, WORKER, NULLIFIER);
        vm.prank(RECEIPT_OPERATOR);
        uint256 gasBefore = gasleft();
        receiptManager.activate(pendingReceiptId);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareReceiptActivateState();
        changedStorageSlotCount = _countChangedSlots(address(receiptManager), baseline.receiptManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessReceiptMarkChallenged()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        prepareReceiptMarkChallengedState();
        bytes32[] memory slots = new bytes32[](1);
        slots[0] = bytes32(uint256(_mappingSlot(pendingReceiptId, 1)) + 5);
        vm.prank(RECEIPT_OPERATOR);
        uint256 gasBefore = gasleft();
        receiptManager.markChallenged(pendingReceiptId);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareReceiptMarkChallengedState();
        changedStorageSlotCount = _countChangedSlots(address(receiptManager), baseline.receiptManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessReceiptSlash()
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        uint256 receiptId = prepareReceiptSlashState();
        bytes32[] memory slots = new bytes32[](1);
        slots[0] = bytes32(uint256(_mappingSlot(receiptId, 1)) + 5);
        vm.prank(RECEIPT_OPERATOR);
        uint256 gasBefore = gasleft();
        receiptManager.slash(receiptId);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareReceiptSlashState();
        changedStorageSlotCount = _countChangedSlots(address(receiptManager), baseline.receiptManagerAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function witnessCreditAllocate(uint256 batchSize)
        public
        returns (uint256 gasUsed, uint256 changedStorageSlotCount, uint256 storageChangeUpperBoundBytes)
    {
        require(batchSize > 0 && batchSize <= 8, "unsupported batch");
        (uint256 taskId, uint256[] memory receiptIds) = prepareCreditAllocateState(batchSize);
        bytes32[] memory slots = _creditSlots(taskId, receiptIds, WORKER);
        vm.prank(CREDIT_OPERATOR);
        uint256 gasBefore = gasleft();
        creditEngine.allocateCredit(taskId, receiptIds);
        gasUsed = gasBefore - gasleft();
        GasSnapshotBaseline baseline = _newBaselineFixture();
        baseline.prepareCreditAllocateState(batchSize);
        changedStorageSlotCount = _countChangedSlots(address(creditEngine), baseline.creditEngineAddress(), slots);
        storageChangeUpperBoundBytes = _storageChangeUpperBoundBytes(changedStorageSlotCount);
    }

    function prepareCommitResponseState() public returns (uint256 taskId) {
        taskId = _createTask(keccak256("gas-commit-task"), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
    }

    function prepareAuditOpenState() public returns (uint256 taskId) {
        taskId = _createTask(keccak256("gas-audit-open"), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
    }

    function prepareOpenedAuditState(bytes32 taskRoot) public returns (uint256 taskId) {
        taskId = _createTask(taskRoot, WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
        vm.prank(AUDITOR);
        auditManager.openAudit(taskId, keccak256("gas-audit-id"), SEED_HASH, POLICY_HASH, 0);
    }

    function prepareReceiptMintPendingState() public returns (uint256 taskId) {
        taskId = _createTask(keccak256("gas-receipt-mint"), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
        _openAcceptedAudit(taskId);
    }

    function prepareReceiptActivateState() public {
        _matureReceiptWindow(consensusTaskId);
    }

    function prepareReceiptMarkChallengedState() public {
        vm.prank(AUDITOR);
        auditManager.openChallenge(consensusTaskId, keccak256("gas-mark-challenged"));
    }

    function prepareReceiptSlashState() public returns (uint256 receiptId) {
        bytes32 nullifier = keccak256("gas-slash-nullifier");
        receiptId = _mintPendingReceipt(nullifier);
        vm.prank(AUDITOR);
        auditManager.openChallenge(consensusTaskId, keccak256("gas-slash-dispute-root"));
        vm.prank(RECEIPT_OPERATOR);
        receiptManager.markChallenged(receiptId);
        vm.prank(AUDITOR);
        auditManager.slash(consensusTaskId);
    }

    function prepareCreditAllocateState(uint256 batchSize) public returns (uint256 taskId, uint256[] memory receiptIds) {
        taskId = _createTask(keccak256(abi.encodePacked("credit-batch", batchSize)), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
        _openAcceptedAudit(taskId);
        receiptIds = new uint256[](batchSize);
        for (uint256 index = 0; index < batchSize; index++) {
            vm.prank(RECEIPT_OPERATOR);
            uint256 receiptId = receiptManager.mintPending(taskId, keccak256(abi.encodePacked("credit-nullifier", batchSize, index)));
            receiptIds[index] = receiptId;
        }
        _matureReceiptWindow(taskId);
        for (uint256 index = 0; index < batchSize; index++) {
            vm.prank(RECEIPT_OPERATOR);
            receiptManager.activate(receiptIds[index]);
        }
    }

    function modelRegistryAddress() public view returns (address) {
        return address(modelRegistry);
    }

    function taskManagerAddress() public view returns (address) {
        return address(taskManager);
    }

    function commitmentHubAddress() public view returns (address) {
        return address(commitmentHub);
    }

    function auditManagerAddress() public view returns (address) {
        return address(auditManager);
    }

    function receiptManagerAddress() public view returns (address) {
        return address(receiptManager);
    }

    function creditEngineAddress() public view returns (address) {
        return address(creditEngine);
    }

    function _newBaselineFixture() internal returns (GasSnapshotBaseline fixture) {
        vmJson.roll(1);
        fixture = new GasSnapshotBaseline();
        fixture.setUp();
    }

    function _countChangedSlots(address afterTarget, address beforeTarget, bytes32[] memory slots)
        internal
        view
        returns (uint256 changedSlots)
    {
        for (uint256 index = 0; index < slots.length; index++) {
            if (vm.load(afterTarget, slots[index]) != vm.load(beforeTarget, slots[index])) {
                changedSlots += 1;
            }
        }
    }

    function _storageChangeUpperBoundBytes(uint256 changedSlots) internal pure returns (uint256) {
        return changedSlots * 32;
    }

    function _mappingSlot(uint256 key, uint256 slot) internal pure returns (bytes32) {
        return keccak256(abi.encode(key, slot));
    }

    function _mappingSlot(bytes32 key, uint256 slot) internal pure returns (bytes32) {
        return keccak256(abi.encode(key, slot));
    }

    function _mappingSlot(address key, uint256 slot) internal pure returns (bytes32) {
        return keccak256(abi.encode(key, slot));
    }

    function _nestedAddressSlot(uint256 outerKey, address innerKey, uint256 slot) internal pure returns (bytes32) {
        return keccak256(abi.encode(innerKey, uint256(keccak256(abi.encode(outerKey, slot)))));
    }

    function _auditSlots(uint256 taskId) internal pure returns (bytes32[] memory slots) {
        bytes32 base = _mappingSlot(taskId, 0);
        slots = new bytes32[](5);
        for (uint256 index = 0; index < 5; index++) {
            slots[index] = bytes32(uint256(base) + index);
        }
    }

    function _receiptMintSlots(uint256 receiptId, bytes32 nullifier) internal pure returns (bytes32[] memory slots) {
        bytes32 base = _mappingSlot(receiptId, 1);
        slots = new bytes32[](8);
        slots[0] = bytes32(uint256(0));
        slots[1] = _mappingSlot(nullifier, 2);
        for (uint256 index = 0; index < 6; index++) {
            slots[index + 2] = bytes32(uint256(base) + index);
        }
    }

    function _receiptActivateSlots(uint256 receiptId, uint256 taskId, address worker, bytes32 nullifier)
        internal
        pure
        returns (bytes32[] memory slots)
    {
        slots = new bytes32[](3);
        slots[0] = _mappingSlot(nullifier, 3);
        slots[1] = bytes32(uint256(_mappingSlot(receiptId, 1)) + 5);
        slots[2] = _nestedAddressSlot(taskId, worker, 4);
    }

    function _creditSlots(uint256 taskId, uint256[] memory receiptIds, address worker)
        internal
        pure
        returns (bytes32[] memory slots)
    {
        slots = new bytes32[](2 + (receiptIds.length * 2));
        slots[0] = _mappingSlot(taskId, 2);
        slots[1] = _nestedAddressSlot(uint256(2), worker, 0);
        for (uint256 index = 0; index < receiptIds.length; index++) {
            slots[2 + (index * 2)] = _mappingSlot(receiptIds[index], 3);
            slots[3 + (index * 2)] = _mappingSlot(receiptIds[index], 4);
        }
    }

}

contract GasSnapshotBaseline is ProtocolKernelBase {
    function modelRegistryAddress() public view returns (address) {
        return address(modelRegistry);
    }

    function taskManagerAddress() public view returns (address) {
        return address(taskManager);
    }

    function commitmentHubAddress() public view returns (address) {
        return address(commitmentHub);
    }

    function auditManagerAddress() public view returns (address) {
        return address(auditManager);
    }

    function receiptManagerAddress() public view returns (address) {
        return address(receiptManager);
    }

    function creditEngineAddress() public view returns (address) {
        return address(creditEngine);
    }

    function prepareCommitResponseState() public returns (uint256 taskId) {
        taskId = _createTask(keccak256("gas-commit-task"), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
    }

    function prepareAuditOpenState() public returns (uint256 taskId) {
        taskId = _createTask(keccak256("gas-audit-open"), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
    }

    function prepareOpenedAuditState(bytes32 taskRoot) public returns (uint256 taskId) {
        taskId = _createTask(taskRoot, WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
        vm.prank(AUDITOR);
        auditManager.openAudit(taskId, keccak256("gas-audit-id"), SEED_HASH, POLICY_HASH, 0);
    }

    function prepareReceiptMintPendingState() public returns (uint256 taskId) {
        taskId = _createTask(keccak256("gas-receipt-mint"), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
        _openAcceptedAudit(taskId);
    }

    function prepareReceiptActivateState() public {
        _matureReceiptWindow(consensusTaskId);
    }

    function prepareReceiptMarkChallengedState() public {
        vm.prank(AUDITOR);
        auditManager.openChallenge(consensusTaskId, keccak256("gas-mark-challenged"));
    }

    function prepareReceiptSlashState() public returns (uint256 receiptId) {
        bytes32 nullifier = keccak256("gas-slash-nullifier");
        receiptId = _mintPendingReceipt(nullifier);
        vm.prank(AUDITOR);
        auditManager.openChallenge(consensusTaskId, keccak256("gas-slash-dispute-root"));
        vm.prank(RECEIPT_OPERATOR);
        receiptManager.markChallenged(receiptId);
        vm.prank(AUDITOR);
        auditManager.slash(consensusTaskId);
    }

    function prepareCreditAllocateState(uint256 batchSize) public returns (uint256 taskId, uint256[] memory receiptIds) {
        taskId = _createTask(keccak256(abi.encodePacked("credit-batch", batchSize)), WORKER, TaskManager.TaskClass.CONSENSUS, 100);
        _commit(taskId, WORKER);
        _finalizeCommitment(taskId);
        _openAcceptedAudit(taskId);
        receiptIds = new uint256[](batchSize);
        for (uint256 index = 0; index < batchSize; index++) {
            vm.prank(RECEIPT_OPERATOR);
            uint256 receiptId = receiptManager.mintPending(taskId, keccak256(abi.encodePacked("credit-nullifier", batchSize, index)));
            receiptIds[index] = receiptId;
        }
        _matureReceiptWindow(taskId);
        for (uint256 index = 0; index < batchSize; index++) {
            vm.prank(RECEIPT_OPERATOR);
            receiptManager.activate(receiptIds[index]);
        }
    }
}

contract GasSnapshotsValidation is ProtocolKernelBase {
    function testWitnessModelRegisterIsDeterministicAcrossFreshFixtures() public {
        GasSnapshots left = new GasSnapshots();
        left.setUp();
        GasSnapshots right = new GasSnapshots();
        right.setUp();
        (uint256 leftGas, uint256 leftSlots, uint256 leftUpperBound) = left.witnessModelRegister();
        (uint256 rightGas, uint256 rightSlots, uint256 rightUpperBound) = right.witnessModelRegister();
        assertEq(leftGas, rightGas, "witnessModelRegister gas must be deterministic across fresh fixtures");
        assertEq(leftSlots, rightSlots, "witnessModelRegister slot count must be deterministic across fresh fixtures");
        assertEq(leftUpperBound, rightUpperBound, "witnessModelRegister upper bound must be deterministic across fresh fixtures");
    }

    function testPackedAuditWriteUsesUpperBoundBytes() public {
        GasSnapshots fixture = new GasSnapshots();
        fixture.setUp();
        (, uint256 changedSlots, uint256 storageUpperBoundBytes) = fixture.witnessAuditRecordResult();
        assertEq(changedSlots, 1, "audit result packed write should affect exactly one storage slot");
        assertEq(storageUpperBoundBytes, 32, "packed audit write must report a one-word upper bound");
    }
}

contract GasSnapshotWitness {
    VmJson internal constant vmJson = VmJson(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external {
        string memory path = string.concat(vmJson.projectRoot(), "/out/e7_foundry_measurements.json");
        string memory measurements = "[";
        measurements = _append(measurements, "MODEL_REGISTER", 1, _modelRegister(), true);
        measurements = _append(measurements, "TASK_CREATE", 1, _taskCreate(), true);
        measurements = _append(measurements, "COMMIT_RESPONSE", 1, _commitResponse(), true);
        measurements = _append(measurements, "AUDIT_OPEN", 1, _auditOpen(), true);
        measurements = _append(measurements, "AUDIT_RECORD_RESULT", 1, _auditRecordResult(), true);
        measurements = _append(measurements, "AUDIT_RECORD_DA", 1, _auditRecordDa(), true);
        measurements = _append(measurements, "OPEN_CHALLENGE", 1, _openChallenge(), true);
        measurements = _append(measurements, "RECEIPT_MINT_PENDING", 1, _receiptMintPending(), true);
        measurements = _append(measurements, "RECEIPT_ACTIVATE", 1, _receiptActivate(), true);
        measurements = _append(measurements, "RECEIPT_MARK_CHALLENGED", 1, _receiptMarkChallenged(), true);
        measurements = _append(measurements, "RECEIPT_SLASH", 1, _receiptSlash(), true);
        measurements = _append(measurements, "CREDIT_ALLOCATE", 1, _creditAllocate(1), true);
        measurements = _append(measurements, "CREDIT_ALLOCATE", 2, _creditAllocate(2), true);
        measurements = _append(measurements, "CREDIT_ALLOCATE", 4, _creditAllocate(4), true);
        measurements = _append(measurements, "CREDIT_ALLOCATE", 8, _creditAllocate(8), false);
        string memory json = string.concat(
            "{",
            "\"schema_version\":\"POI_MPP_E7_FOUNDRY_REPORT_V1\",",
            "\"test_contract\":\"GasSnapshots\",",
            "\"witness_contract\":\"GasSnapshotWitness\",",
            "\"chain_id\":",
            vmJson.toString(block.chainid),
            ",",
            "\"block_gas_limit\":",
            vmJson.toString(block.gaslimit),
            ",",
            "\"measurements\":",
            measurements,
            "}"
        );
        vmJson.writeJson(json, path);
    }

    function _append(
        string memory current,
        string memory operation,
        uint256 batchSize,
        uint256[3] memory result,
        bool trailingComma
    ) internal pure returns (string memory) {
        return string.concat(
            current,
            _measurementJson(operation, batchSize, result[0], result[1], result[2]),
            trailingComma ? "," : "]"
        );
    }

    function _measurementJson(
        string memory operation,
        uint256 batchSize,
        uint256 gasUsed,
        uint256 changedStorageSlotCount,
        uint256 storageChangeUpperBoundBytes
    )
        internal
        pure
        returns (string memory)
    {
        return string.concat(
            "{",
            "\"operation\":\"",
            operation,
            "\",",
            "\"batch_size\":",
            vmJson.toString(batchSize),
            ",",
            "\"gas_used\":",
            vmJson.toString(gasUsed),
            ",",
            "\"changed_storage_slot_count\":",
            vmJson.toString(changedStorageSlotCount),
            ",",
            "\"storage_change_upper_bound_bytes\":",
            vmJson.toString(storageChangeUpperBoundBytes),
            "}"
        );
    }

    function _newFixture() internal returns (GasSnapshots fixture) {
        vmJson.roll(1);
        fixture = new GasSnapshots();
        fixture.setUp();
    }

    function _modelRegister() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessModelRegister();
    }

    function _taskCreate() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessTaskCreate();
    }

    function _commitResponse() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessCommitResponse();
    }

    function _auditOpen() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessAuditOpen();
    }

    function _auditRecordResult() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessAuditRecordResult();
    }

    function _auditRecordDa() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessAuditRecordDa();
    }

    function _openChallenge() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessOpenChallenge();
    }

    function _receiptMintPending() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessReceiptMintPending();
    }

    function _receiptActivate() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessReceiptActivate();
    }

    function _receiptMarkChallenged() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessReceiptMarkChallenged();
    }

    function _receiptSlash() internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessReceiptSlash();
    }

    function _creditAllocate(uint256 batchSize) internal returns (uint256[3] memory result) {
        GasSnapshots fixture = _newFixture();
        (result[0], result[1], result[2]) = fixture.witnessCreditAllocate(batchSize);
    }
}
