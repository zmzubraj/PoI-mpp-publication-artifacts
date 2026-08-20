// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./PolicyRegistry.sol";
import "./TaskManager.sol";
import "./ReceiptManager.sol";

contract CreditEngine {
    error CreditEngine__ActiveReceiptCountMismatch();
    error CreditEngine__BudgetExceeded();
    error CreditEngine__NoActiveReceipt();
    error CreditEngine__ReceiptAlreadyCredited();
    error CreditEngine__ReceiptIdsNotStrictlyAscending();
    error CreditEngine__ReceiptMissing();
    error CreditEngine__ReceiptNotActive();
    error CreditEngine__ReceiptTaskMismatch();
    error CreditEngine__ReceiptWrongEpoch();
    error CreditEngine__TaskNotCreditable();
    error CreditEngine__Unauthorized();
    error CreditEngine__WorkerMismatch();

    uint16 public constant EVENT_VERSION = 1;

    PolicyRegistry public immutable policy;
    TaskManager public immutable taskManager;
    ReceiptManager public immutable receiptManager;

    mapping(uint64 => mapping(address => uint256)) public rawCredit;
    mapping(address => uint256) public collateral;

    mapping(uint256 => uint256) public taskAllocated;
    mapping(uint256 => bool) public creditedReceipts;
    mapping(uint256 => uint256) public receiptCredit;

    event CollateralSetV1(uint16 indexed version, address indexed worker, uint256 amount);
    event CreditAddedV1(
        uint16 indexed version,
        uint256 indexed taskId,
        uint64 indexed epoch,
        uint256 receiptId,
        address worker,
        uint256 credit,
        uint256 cumulativeTaskCredit
    );

    constructor(address policy_, address taskManager_, address receiptManager_) {
        policy = PolicyRegistry(policy_);
        taskManager = TaskManager(taskManager_);
        receiptManager = ReceiptManager(receiptManager_);
    }

    modifier onlyCreditOperator() {
        if (!policy.hasRole(policy.CREDIT_OPERATOR_ROLE(), msg.sender)) {
            revert CreditEngine__Unauthorized();
        }
        _;
    }

    function setCollateral(address worker, uint256 amount) external onlyCreditOperator {
        collateral[worker] = amount;
        emit CollateralSetV1(EVENT_VERSION, worker, amount);
    }

    function allocateCredit(uint256 taskId, uint256[] calldata receiptIds) external onlyCreditOperator {
        TaskManager.Task memory task = taskManager.getTask(taskId);
        if (
            !task.active || !task.registered || task.taskClass != TaskManager.TaskClass.CONSENSUS
                || task.creditBudget == 0
        ) {
            return;
        }
        if (receiptIds.length == 0) {
            revert CreditEngine__NoActiveReceipt();
        }
        address worker = task.worker;
        if (!taskManager.isRegisteredWorker(worker)) {
            revert CreditEngine__WorkerMismatch();
        }
        uint256 activeCount = receiptManager.activeReceiptCount(taskId, worker);
        if (activeCount == 0) {
            revert CreditEngine__NoActiveReceipt();
        }
        if (receiptIds.length != activeCount) {
            revert CreditEngine__ActiveReceiptCountMismatch();
        }

        uint256 baseShare = task.creditBudget / receiptIds.length;
        uint256 remainder = task.creditBudget % receiptIds.length;
        uint64 creditEpoch = task.epoch + 1;
        uint256 previousReceiptId;
        uint256 allocated = taskAllocated[taskId];
        for (uint256 index = 0; index < receiptIds.length; index++) {
            uint256 receiptId = receiptIds[index];
            if (index > 0 && receiptId <= previousReceiptId) {
                revert CreditEngine__ReceiptIdsNotStrictlyAscending();
            }
            previousReceiptId = receiptId;
            uint256 share = baseShare + (index < remainder ? 1 : 0);
            allocated = _allocateReceiptCredit(
                taskId, task.epoch, task.creditBudget, worker, creditEpoch, receiptId, share, allocated
            );
        }
        taskAllocated[taskId] = allocated;
    }

    function _allocateReceiptCredit(
        uint256 taskId,
        uint64 taskEpoch,
        uint256 taskCreditBudget,
        address worker,
        uint64 creditEpoch,
        uint256 receiptId,
        uint256 share,
        uint256 allocated
    ) private returns (uint256 nextAllocated) {
        ReceiptManager.Receipt memory receipt = receiptManager.getReceipt(receiptId);
        if (receipt.taskId == 0 || receipt.worker == address(0)) {
            revert CreditEngine__ReceiptMissing();
        }
        if (receipt.taskId != taskId) {
            revert CreditEngine__ReceiptTaskMismatch();
        }
        if (receipt.worker != worker) {
            revert CreditEngine__WorkerMismatch();
        }
        if (receipt.state != ReceiptManager.State.ACTIVE) {
            revert CreditEngine__ReceiptNotActive();
        }
        if (receipt.activatedEpoch != taskEpoch + 1) {
            revert CreditEngine__ReceiptWrongEpoch();
        }
        if (creditedReceipts[receiptId]) {
            revert CreditEngine__ReceiptAlreadyCredited();
        }

        nextAllocated = allocated + share;
        if (nextAllocated > taskCreditBudget) {
            revert CreditEngine__BudgetExceeded();
        }

        creditedReceipts[receiptId] = true;
        receiptCredit[receiptId] = share;
        rawCredit[creditEpoch][worker] += share;
        emit CreditAddedV1(EVENT_VERSION, taskId, creditEpoch, receiptId, worker, share, nextAllocated);
    }

    function activeWeight(uint64 epoch, address worker) external view returns (uint256) {
        uint256 q = rawCredit[epoch][worker];
        uint256 workerCollateral = collateral[worker];
        uint256 cap = policy.concentrationCap();
        if (q == 0 || workerCollateral == 0 || cap == 0) {
            return 0;
        }

        uint256 collateralCap = workerCollateral / policy.beta();
        if (collateralCap == 0) {
            return 0;
        }

        uint256 bounded = q < collateralCap ? q : collateralCap;
        return bounded < cap ? bounded : cap;
    }
}
