// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract TaskManager {
    enum TaskClass { SERVICE, CONSENSUS }
    struct Task { bytes32 taskRoot; bytes32 modelRoot; TaskClass taskClass; uint256 creditBudget; uint64 deadline; bool active; }
    uint256 public nextTaskId = 1;
    mapping(uint256 => Task) public tasks;
    event TaskCreated(uint256 indexed taskId, bytes32 taskRoot, bytes32 modelRoot, TaskClass taskClass, uint256 creditBudget);
    function createTask(bytes32 taskRoot, bytes32 modelRoot, TaskClass taskClass, uint256 creditBudget, uint64 deadline) external returns (uint256 id) {
        id = nextTaskId++;
        tasks[id] = Task(taskRoot, modelRoot, taskClass, creditBudget, deadline, true);
        emit TaskCreated(id, taskRoot, modelRoot, taskClass, creditBudget);
    }
}
