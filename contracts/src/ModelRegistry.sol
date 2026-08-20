// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract ModelRegistry {
    struct Model { bytes32 modelRoot; bytes32 runtimeRoot; uint8 assuranceClass; bool active; }
    mapping(bytes32 => Model) public models;
    event ModelRegistered(bytes32 indexed modelRoot, bytes32 runtimeRoot, uint8 assuranceClass);
    function registerModel(bytes32 modelRoot, bytes32 runtimeRoot, uint8 assuranceClass) external {
        require(modelRoot != bytes32(0), "model root");
        models[modelRoot] = Model(modelRoot, runtimeRoot, assuranceClass, true);
        emit ModelRegistered(modelRoot, runtimeRoot, assuranceClass);
    }
}
