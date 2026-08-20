// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract PolicyRegistry {
    error PolicyRegistry__InvalidAddress();
    error PolicyRegistry__InvalidPolicyValue();
    error PolicyRegistry__Unauthorized();

    uint16 public constant EVENT_VERSION = 1;

    bytes32 public constant MODEL_ADMIN_ROLE = keccak256("MODEL_ADMIN_ROLE");
    bytes32 public constant TASK_ADMIN_ROLE = keccak256("TASK_ADMIN_ROLE");
    bytes32 public constant AUDITOR_ROLE = keccak256("AUDITOR_ROLE");
    bytes32 public constant RECEIPT_OPERATOR_ROLE = keccak256("RECEIPT_OPERATOR_ROLE");
    bytes32 public constant CREDIT_OPERATOR_ROLE = keccak256("CREDIT_OPERATOR_ROLE");

    address public immutable owner;

    mapping(bytes32 => mapping(address => bool)) private _roles;

    address public modelRegistry;
    address public taskManager;
    address public commitmentHub;
    address public auditManager;
    address public receiptManager;
    address public creditEngine;

    uint64 public commitmentFinalityDepth;
    uint64 public challengeWindowBlocks;
    uint256 public beta;
    uint256 public concentrationCap;

    event RoleGrantedV1(uint16 indexed version, bytes32 indexed role, address indexed account);
    event RoleRevokedV1(uint16 indexed version, bytes32 indexed role, address indexed account);
    event DependencyUpdatedV1(uint16 indexed version, bytes32 indexed dependency, address indexed target);
    event PolicyParameterUpdatedV1(uint16 indexed version, bytes32 indexed parameter, uint256 value);

    constructor(
        uint64 commitmentFinalityDepth_,
        uint64 challengeWindowBlocks_,
        uint256 beta_,
        uint256 concentrationCap_
    ) {
        owner = msg.sender;
        _setPolicy(commitmentFinalityDepth_, challengeWindowBlocks_, beta_, concentrationCap_);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) {
            revert PolicyRegistry__Unauthorized();
        }
        _;
    }

    function hasRole(bytes32 role, address account) external view returns (bool) {
        return _roles[role][account];
    }

    function grantRole(bytes32 role, address account) external onlyOwner {
        if (account == address(0)) {
            revert PolicyRegistry__InvalidAddress();
        }
        _roles[role][account] = true;
        emit RoleGrantedV1(EVENT_VERSION, role, account);
    }

    function revokeRole(bytes32 role, address account) external onlyOwner {
        _roles[role][account] = false;
        emit RoleRevokedV1(EVENT_VERSION, role, account);
    }

    function setModelRegistry(address target) external onlyOwner {
        modelRegistry = _setDependency(keccak256("modelRegistry"), target);
    }

    function setTaskManager(address target) external onlyOwner {
        taskManager = _setDependency(keccak256("taskManager"), target);
    }

    function setCommitmentHub(address target) external onlyOwner {
        commitmentHub = _setDependency(keccak256("commitmentHub"), target);
    }

    function setAuditManager(address target) external onlyOwner {
        auditManager = _setDependency(keccak256("auditManager"), target);
    }

    function setReceiptManager(address target) external onlyOwner {
        receiptManager = _setDependency(keccak256("receiptManager"), target);
    }

    function setCreditEngine(address target) external onlyOwner {
        creditEngine = _setDependency(keccak256("creditEngine"), target);
    }

    function setProtocolPolicy(
        uint64 commitmentFinalityDepth_,
        uint64 challengeWindowBlocks_,
        uint256 beta_,
        uint256 concentrationCap_
    ) external onlyOwner {
        _setPolicy(commitmentFinalityDepth_, challengeWindowBlocks_, beta_, concentrationCap_);
    }

    function _setDependency(bytes32 dependency, address target) private returns (address) {
        if (target == address(0)) {
            revert PolicyRegistry__InvalidAddress();
        }
        emit DependencyUpdatedV1(EVENT_VERSION, dependency, target);
        return target;
    }

    function _setPolicy(
        uint64 commitmentFinalityDepth_,
        uint64 challengeWindowBlocks_,
        uint256 beta_,
        uint256 concentrationCap_
    ) private {
        if (commitmentFinalityDepth_ == 0 || challengeWindowBlocks_ == 0 || beta_ == 0 || concentrationCap_ == 0) {
            revert PolicyRegistry__InvalidPolicyValue();
        }
        commitmentFinalityDepth = commitmentFinalityDepth_;
        challengeWindowBlocks = challengeWindowBlocks_;
        beta = beta_;
        concentrationCap = concentrationCap_;
        emit PolicyParameterUpdatedV1(EVENT_VERSION, keccak256("commitmentFinalityDepth"), commitmentFinalityDepth_);
        emit PolicyParameterUpdatedV1(EVENT_VERSION, keccak256("challengeWindowBlocks"), challengeWindowBlocks_);
        emit PolicyParameterUpdatedV1(EVENT_VERSION, keccak256("beta"), beta_);
        emit PolicyParameterUpdatedV1(EVENT_VERSION, keccak256("concentrationCap"), concentrationCap_);
    }
}
