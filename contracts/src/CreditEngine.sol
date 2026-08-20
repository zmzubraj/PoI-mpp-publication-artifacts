// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./PolicyRegistry.sol";
import "./TaskManager.sol";
import "./ReceiptManager.sol";

contract CreditEngine {
    error CreditEngine__BudgetExceeded();
    error CreditEngine__NoActiveReceipt();
    error CreditEngine__ReceiptAlreadyCredited();
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

    function addCredit(uint256 taskId, uint256 receiptId, address worker, uint256 credit) external onlyCreditOperator {
        TaskManager.Task memory task = taskManager.getTask(taskId);
        if (!task.active || !task.registered || task.taskClass != TaskManager.TaskClass.CONSENSUS) {
            revert CreditEngine__TaskNotCreditable();
        }

        ReceiptManager.Receipt memory receipt = receiptManager.getReceipt(receiptId);
        if (receipt.taskId == 0 || receipt.worker == address(0)) {
            revert CreditEngine__ReceiptMissing();
        }
        if (receipt.taskId != taskId) {
            revert CreditEngine__ReceiptTaskMismatch();
        }
        if (worker != task.worker || worker != receipt.worker || !taskManager.isRegisteredWorker(worker)) {
            revert CreditEngine__WorkerMismatch();
        }
        if (receipt.state != ReceiptManager.State.ACTIVE) {
            revert CreditEngine__ReceiptNotActive();
        }
        if (receipt.activatedEpoch != task.epoch + 1) {
            revert CreditEngine__ReceiptWrongEpoch();
        }
        if (creditedReceipts[receiptId]) {
            revert CreditEngine__ReceiptAlreadyCredited();
        }
        if (receiptManager.activeReceiptCount(taskId, worker) == 0) {
            revert CreditEngine__NoActiveReceipt();
        }

        uint256 nextAllocated = taskAllocated[taskId] + credit;
        if (nextAllocated > task.creditBudget) {
            revert CreditEngine__BudgetExceeded();
        }
        creditedReceipts[receiptId] = true;
        taskAllocated[taskId] = nextAllocated;
        uint64 creditEpoch = task.epoch + 1;
        rawCredit[creditEpoch][worker] += credit;
        emit CreditAddedV1(EVENT_VERSION, taskId, creditEpoch, receiptId, worker, credit, nextAllocated);
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
