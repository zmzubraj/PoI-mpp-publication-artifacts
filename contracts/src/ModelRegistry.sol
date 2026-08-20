// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./PolicyRegistry.sol";
import "./ProtocolHashing.sol";

contract ModelRegistry {
    error ModelRegistry__AlreadyRegistered();
    error ModelRegistry__InvalidRoot();
    error ModelRegistry__ModelNotFound();
    error ModelRegistry__Unauthorized();

    uint16 public constant EVENT_VERSION = 1;

    PolicyRegistry public immutable policy;

    struct Model {
        bytes32 modelRoot;
        bytes32 runtimeRoot;
        bytes32 modelManifestHash;
        uint8 assuranceClass;
        bool active;
    }

    mapping(bytes32 => Model) public models;

    event ModelRegisteredV1(
        uint16 indexed version,
        bytes32 indexed modelRoot,
        bytes32 runtimeRoot,
        bytes32 modelManifestHash,
        uint8 assuranceClass
    );
    event ModelDeactivatedV1(uint16 indexed version, bytes32 indexed modelRoot);

    constructor(address policy_) {
        policy = PolicyRegistry(policy_);
    }

    modifier onlyModelAdmin() {
        if (!policy.hasRole(policy.MODEL_ADMIN_ROLE(), msg.sender)) {
            revert ModelRegistry__Unauthorized();
        }
        _;
    }

    function registerModel(bytes32 modelRoot, bytes32 runtimeRoot, bytes32 modelManifestHash, uint8 assuranceClass)
        external
        onlyModelAdmin
    {
        if (modelRoot == bytes32(0) || runtimeRoot == bytes32(0) || modelManifestHash == bytes32(0)) {
            revert ModelRegistry__InvalidRoot();
        }
        if (models[modelRoot].active) {
            revert ModelRegistry__AlreadyRegistered();
        }
        models[modelRoot] = Model(modelRoot, runtimeRoot, modelManifestHash, assuranceClass, true);
        emit ModelRegisteredV1(EVENT_VERSION, modelRoot, runtimeRoot, modelManifestHash, assuranceClass);
    }

    function deactivateModel(bytes32 modelRoot) external onlyModelAdmin {
        if (!models[modelRoot].active) {
            revert ModelRegistry__ModelNotFound();
        }
        models[modelRoot].active = false;
        emit ModelDeactivatedV1(EVENT_VERSION, modelRoot);
    }

    function isRegisteredModel(bytes32 modelRoot) external view returns (bool) {
        return models[modelRoot].active;
    }

    function modelCommitment(bytes32 modelRoot) external view returns (bytes32) {
        Model memory model = models[modelRoot];
        if (!model.active) {
            revert ModelRegistry__ModelNotFound();
        }
        return ProtocolHashing.modelCommitment(
            model.modelRoot, model.runtimeRoot, model.modelManifestHash, model.assuranceClass
        );
    }
}
