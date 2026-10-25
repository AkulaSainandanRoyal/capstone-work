// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity 0.8.19;

/// @notice Chainlink-style price feed with a settable answer, for oracle overrides on a fork.
/// @dev Installed with anvil_setCode (no constructor runs), so the answer lives in storage slot 0 and is set
///      with a storage write or `setAnswer`. 18 decimals, matching the Pendle feeds it replaces.
///      `updatedAt` is always block.timestamp so staleness checks (e.g. OjoPTFeed's 24 h) pass.
contract MockAggregator {
    int256 public answer; // slot 0

    function setAnswer(int256 newAnswer) external {
        answer = newAnswer;
    }

    function decimals() external pure returns (uint8) {
        return 18;
    }

    function description() external pure returns (string memory) {
        return "LAPEG mock aggregator";
    }

    function version() external pure returns (uint256) {
        return 1;
    }

    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80) {
        return (0, answer, block.timestamp, block.timestamp, 0);
    }
}
