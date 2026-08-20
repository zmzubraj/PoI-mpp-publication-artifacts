// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./PolicyRegistry.sol";
import "./ModelRegistry.sol";

contract TaskManager {
    error TaskManager__EpochMismatch();
    error TaskManager__InvalidTask();
    error TaskManager__ModelNotRegistered();
    error TaskManager__Unauthorized();
    error TaskManager__WorkerNotRegistered();

    uint16 public constant EVENT_VERSION = 1;

    enum TaskClass {
        SERVICE,
        CONSENSUS
    }

    PolicyRegistry public immutable policy;
    ModelRegistry public immutable modelRegistry;

    struct Task {
        bytes32 taskRoot;
        bytes32 modelRoot;
        address worker;
        TaskClass taskClass;
        uint256 creditBudget;
        uint64 epoch;
        uint64 deadline;
        bool active;
        bool registered;
    }

    uint256 public nextTaskId = 1;
    mapping(uint256 => Task) public tasks;

    mapping(address => bool) public registeredWorkers;

    event WorkerRegisteredV1(uint16 indexed version, address indexed worker);
    event TaskCreatedV1(
        uint16 indexed version,
        uint256 indexed taskId,
        address indexed worker,
        bytes32 taskRoot,
        bytes32 modelRoot,
        TaskClass taskClass,
        uint256 creditBudget,
        uint64 epoch,
        uint64 deadline
    );

    constructor(address policy_, address modelRegistry_) {
        policy = PolicyRegistry(policy_);
        modelRegistry = ModelRegistry(modelRegistry_);
    }

    modifier onlyTaskAdmin() {
        if (!policy.hasRole(policy.TASK_ADMIN_ROLE(), msg.sender)) {
            revert TaskManager__Unauthorized();
        }
        _;
    }

    function registerWorker(address worker) external onlyTaskAdmin {
        if (worker == address(0)) {
            revert TaskManager__InvalidTask();
        }
        registeredWorkers[worker] = true;
        emit WorkerRegisteredV1(EVENT_VERSION, worker);
    }

    function createTask(
        bytes32 taskRoot,
        bytes32 modelRoot,
        address worker,
        TaskClass taskClass,
        uint256 creditBudget,
        uint64 epoch,
        uint64 deadline
    ) external onlyTaskAdmin returns (uint256 id) {
        if (taskRoot == bytes32(0) || worker == address(0) || deadline == 0) {
            revert TaskManager__InvalidTask();
        }
        if (!registeredWorkers[worker]) {
            revert TaskManager__WorkerNotRegistered();
        }
        if (!modelRegistry.isRegisteredModel(modelRoot)) {
            revert TaskManager__ModelNotRegistered();
        }
        if (epoch != policy.currentEpoch()) {
            revert TaskManager__EpochMismatch();
        }
        id = nextTaskId++;
        tasks[id] = Task(taskRoot, modelRoot, worker, taskClass, creditBudget, epoch, deadline, true, true);
        emit TaskCreatedV1(EVENT_VERSION, id, worker, taskRoot, modelRoot, taskClass, creditBudget, epoch, deadline);
    }

    function isRegisteredTask(uint256 taskId) external view returns (bool) {
        Task memory task = tasks[taskId];
        return task.active && task.registered;
    }

    function isRegisteredWorker(address worker) external view returns (bool) {
        return registeredWorkers[worker];
    }

    function getTask(uint256 taskId) external view returns (Task memory) {
        return tasks[taskId];
    }
}
