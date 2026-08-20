// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract CreditEngine {
    mapping(uint64 => mapping(address => uint256)) public rawCredit;
    mapping(address => uint256) public collateral;
    uint256 public beta = 10;
    event CreditAdded(uint64 indexed epoch, address indexed worker, uint256 credit);
    function setCollateral(address worker, uint256 amount) external { collateral[worker] = amount; }
    function addCredit(uint64 epoch, address worker, uint256 credit) external {
        rawCredit[epoch][worker] += credit;
        emit CreditAdded(epoch, worker, credit);
    }
    function activeWeight(uint64 epoch, address worker) external view returns (uint256) {
        uint256 q = rawCredit[epoch][worker];
        uint256 cap = collateral[worker] / beta;
        return q < cap ? q : cap;
    }
}
