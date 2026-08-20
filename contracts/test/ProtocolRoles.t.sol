// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../src/PolicyRegistry.sol";
import "../src/ModelRegistry.sol";
import "../src/TaskManager.sol";
import "../src/CommitmentHub.sol";
import "../src/AuditManager.sol";
import "../src/ReceiptManager.sol";
import "../src/CreditEngine.sol";

interface Vm {
    function prank(address caller) external;
    function startPrank(address caller) external;
    function stopPrank() external;
    function expectRevert() external;
    function expectRevert(bytes4 revertData) external;
    function expectRevert(bytes calldata revertData) external;
    function roll(uint256 newHeight) external;
    function assume(bool condition) external;
    function load(address target, bytes32 slot) external view returns (bytes32 data);
    function store(address target, bytes32 slot, bytes32 value) external;
}

abstract contract MinimalTest {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function assertTrue(bool condition, string memory message) internal pure {
        require(condition, message);
    }

    function assertEq(uint256 left, uint256 right, string memory message) internal pure {
        require(left == right, message);
    }

    function assertEq(address left, address right, string memory message) internal pure {
        require(left == right, message);
    }

    function assertEq(bytes32 left, bytes32 right, string memory message) internal pure {
        require(left == right, message);
    }
}

abstract contract ProtocolKernelBase is MinimalTest {
    uint64 internal constant GENESIS_BLOCK = 1;
    uint64 internal constant BLOCKS_PER_EPOCH = 5;

    address internal constant MODEL_ADMIN = address(0x1001);
    address internal constant TASK_ADMIN = address(0x1002);
    address internal constant AUDITOR = address(0x1003);
    address internal constant RECEIPT_OPERATOR = address(0x1004);
    address internal constant CREDIT_OPERATOR = address(0x1005);
    address internal constant WORKER = address(0x2001);
    address internal constant ALT_WORKER = address(0x2002);
    address internal constant ATTACKER = address(0x3001);

    bytes32 internal constant MODEL_ROOT = keccak256("model-root");
    bytes32 internal constant RUNTIME_ROOT = keccak256("runtime-root");
    bytes32 internal constant MODEL_MANIFEST_HASH = keccak256("model-manifest");
    bytes32 internal constant TASK_ROOT = keccak256("task-root");
    bytes32 internal constant SERVICE_TASK_ROOT = keccak256("service-task-root");
    bytes32 internal constant RESPONSE_ROOT = keccak256("response-root");
    bytes32 internal constant TRACE_ROOT = keccak256("trace-root");
    bytes32 internal constant EVIDENCE_ROOT = keccak256("evidence-root");
    bytes32 internal constant ARTIFACT_ROOT = keccak256("artifact-root");
    bytes32 internal constant NONCE = keccak256("nonce");
    bytes32 internal constant AUDIT_ID = keccak256("audit-id");
    bytes32 internal constant SEED_HASH = keccak256("seed-hash");
    bytes32 internal constant POLICY_HASH = keccak256("policy-hash");
    bytes32 internal constant NULLIFIER = keccak256("nullifier");

    PolicyRegistry internal policy;
    ModelRegistry internal modelRegistry;
    TaskManager internal taskManager;
    CommitmentHub internal commitmentHub;
    AuditManager internal auditManager;
    ReceiptManager internal receiptManager;
    CreditEngine internal creditEngine;

    uint256 internal consensusTaskId;
    uint256 internal serviceTaskId;
    uint256 internal pendingReceiptId;

    function setUp() public virtual {
        policy = new PolicyRegistry(2, 5, 10, 1_000, GENESIS_BLOCK, BLOCKS_PER_EPOCH);
        modelRegistry = new ModelRegistry(address(policy));
        taskManager = new TaskManager(address(policy), address(modelRegistry));
        commitmentHub = new CommitmentHub(address(policy), address(taskManager));
        auditManager = new AuditManager(address(policy), address(commitmentHub), address(taskManager));
        receiptManager =
            new ReceiptManager(address(policy), address(taskManager), address(commitmentHub), address(auditManager));
        creditEngine = new CreditEngine(address(policy), address(taskManager), address(receiptManager));

        policy.grantRole(policy.MODEL_ADMIN_ROLE(), MODEL_ADMIN);
        policy.grantRole(policy.TASK_ADMIN_ROLE(), TASK_ADMIN);
        policy.grantRole(policy.AUDITOR_ROLE(), AUDITOR);
        policy.grantRole(policy.RECEIPT_OPERATOR_ROLE(), RECEIPT_OPERATOR);
        policy.grantRole(policy.CREDIT_OPERATOR_ROLE(), CREDIT_OPERATOR);

        policy.setModelRegistry(address(modelRegistry));
        policy.setTaskManager(address(taskManager));
        policy.setCommitmentHub(address(commitmentHub));
        policy.setAuditManager(address(auditManager));
        policy.setReceiptManager(address(receiptManager));
        policy.setCreditEngine(address(creditEngine));

        vm.prank(MODEL_ADMIN);
        modelRegistry.registerModel(MODEL_ROOT, RUNTIME_ROOT, MODEL_MANIFEST_HASH, 1);

        vm.startPrank(TASK_ADMIN);
        taskManager.registerWorker(WORKER);
        taskManager.registerWorker(ALT_WORKER);
        consensusTaskId = taskManager.createTask(
            TASK_ROOT, MODEL_ROOT, WORKER, TaskManager.TaskClass.CONSENSUS, 100, policy.currentEpoch(), 500
        );
        serviceTaskId = taskManager.createTask(
            SERVICE_TASK_ROOT, MODEL_ROOT, ALT_WORKER, TaskManager.TaskClass.SERVICE, 100, policy.currentEpoch(), 500
        );
        vm.stopPrank();

        _commit(consensusTaskId, WORKER);
        _finalizeCommitment(consensusTaskId);
        _openAcceptedAudit(consensusTaskId);

        vm.prank(RECEIPT_OPERATOR);
        pendingReceiptId = receiptManager.mintPending(consensusTaskId, NULLIFIER);
    }

    function _commit(uint256 taskId, address worker) internal {
        vm.prank(worker);
        commitmentHub.commitResponse(taskId, RESPONSE_ROOT, TRACE_ROOT, EVIDENCE_ROOT, ARTIFACT_ROOT, NONCE);
    }

    function _finalizeCommitment(uint256 taskId) internal {
        CommitmentHub.Commitment memory committed = commitmentHub.getCommitment(taskId);
        vm.roll(uint256(committed.finalizedBlock));
    }

    function _openAcceptedAudit(uint256 taskId) internal {
        vm.startPrank(AUDITOR);
        auditManager.openAudit(taskId, AUDIT_ID, SEED_HASH, POLICY_HASH, 0);
        auditManager.recordAuditResult(taskId, AuditManager.AuditDecision.ACCEPT);
        auditManager.recordDataAvailability(taskId, true);
        vm.stopPrank();
    }

    function _matureReceiptWindow(uint256 taskId) internal {
        AuditManager.AuditRound memory round = auditManager.getAudit(taskId);
        vm.roll(uint256(round.challengeDeadline));
    }

    function _activatePendingReceipt(uint256 receiptId) internal {
        vm.prank(RECEIPT_OPERATOR);
        receiptManager.activate(receiptId);
    }

    function _mintPendingReceipt(bytes32 nullifier) internal returns (uint256 receiptId) {
        vm.prank(RECEIPT_OPERATOR);
        receiptId = receiptManager.mintPending(consensusTaskId, nullifier);
    }

    function _createTask(bytes32 taskRoot, address worker, TaskManager.TaskClass taskClass, uint256 creditBudget)
        internal
        returns (uint256 taskId)
    {
        uint64 currentEpoch = policy.currentEpoch();
        vm.prank(TASK_ADMIN);
        taskId = taskManager.createTask(taskRoot, MODEL_ROOT, worker, taskClass, creditBudget, currentEpoch, 500);
    }

    function _prepareTaskWithActiveReceipt(uint256 taskId, address worker, bytes32 nullifier)
        internal
        returns (uint256)
    {
        _commit(taskId, worker);
        _finalizeCommitment(taskId);
        _openAcceptedAudit(taskId);
        vm.prank(RECEIPT_OPERATOR);
        uint256 receiptId = receiptManager.mintPending(taskId, nullifier);
        _matureReceiptWindow(taskId);
        _activatePendingReceipt(receiptId);
        return receiptId;
    }

    function _setTaskActive(uint256 taskId, bool active_) internal {
        bytes32 slot = bytes32(uint256(keccak256(abi.encode(taskId, uint256(1)))) + 4);
        uint256 packed = uint256(vm.load(address(taskManager), slot));
        uint256 activeMask = uint256(0xff) << 128;
        uint256 nextPacked = active_ ? (packed | activeMask) : (packed & ~activeMask);
        vm.store(address(taskManager), slot, bytes32(nextPacked));
    }

    function _setTaskEpoch(uint256 taskId, uint64 epoch) internal {
        bytes32 slot = bytes32(uint256(keccak256(abi.encode(taskId, uint256(1)))) + 4);
        uint256 packed = uint256(vm.load(address(taskManager), slot));
        uint256 nextPacked = (packed & ~uint256(type(uint64).max)) | uint256(epoch);
        vm.store(address(taskManager), slot, bytes32(nextPacked));
    }
}

contract ProtocolRolesTest is ProtocolKernelBase {
    function testUnauthorizedCallerCannotAllocateCredit() public {
        vm.prank(ATTACKER);
        vm.expectRevert(CreditEngine.CreditEngine__Unauthorized.selector);
        uint256[] memory receiptIds = new uint256[](1);
        receiptIds[0] = pendingReceiptId;
        creditEngine.allocateCredit(consensusTaskId, receiptIds);
    }

    function testOnlyRegisteredWorkerCanCommitTask() public {
        vm.prank(ATTACKER);
        vm.expectRevert(CommitmentHub.CommitmentHub__WorkerMismatch.selector);
        commitmentHub.commitResponse(serviceTaskId, RESPONSE_ROOT, TRACE_ROOT, EVIDENCE_ROOT, ARTIFACT_ROOT, NONCE);
    }

    function testOnlyTaskAdminCanRegisterWorker() public {
        vm.prank(ATTACKER);
        vm.expectRevert(TaskManager.TaskManager__Unauthorized.selector);
        taskManager.registerWorker(address(0x7777));
    }

    function testOnlyModelAdminCanRegisterModel() public {
        vm.prank(ATTACKER);
        vm.expectRevert(ModelRegistry.ModelRegistry__Unauthorized.selector);
        modelRegistry.registerModel(keccak256("unauthorized-model"), RUNTIME_ROOT, MODEL_MANIFEST_HASH, 2);
    }

    function testRejectsFutureTaskEpochOutsideCanonicalCurrentEpoch() public {
        uint64 futureEpoch = policy.currentEpoch() + 7;
        vm.startPrank(TASK_ADMIN);
        vm.expectRevert(TaskManager.TaskManager__EpochMismatch.selector);
        taskManager.createTask(
            keccak256("future-task-root"), MODEL_ROOT, WORKER, TaskManager.TaskClass.CONSENSUS, 100, futureEpoch, 500
        );
        vm.stopPrank();
    }
}
