import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfigForm from "./ConfigForm";

// --------------------------------------------------------------------------
// Mocks
// --------------------------------------------------------------------------

vi.mock("@/hooks/queries/use-registry", () => ({
  useResources: () => ({ data: [] }),
}));

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

function makeValues(overrides: Record<string, unknown> = {}) {
  return {
    orchestrator: { role: "imu", permission_mode: "default" },
    runtime: "strawpot-claude-code",
    ...overrides,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let onSave: any;

beforeEach(() => {
  onSave = vi.fn();
});

function renderForm(
  valuesOverrides: Record<string, unknown> = {},
  props: { saving?: boolean; showQuickSwitch?: boolean } = {},
) {
  const values = makeValues(valuesOverrides);
  return render(
    <ConfigForm
      values={values}
      onSave={onSave}
      saving={props.saving}
      showQuickSwitch={props.showQuickSwitch}
    />,
  );
}

/** Get the quick-switch container (the one with "Quick switch" label). */
function getQuickSwitchButtons() {
  const label = screen.getByText("Quick switch");
  const container = label.closest("div")!.parentElement!;
  return within(container).getAllByRole("button");
}

// --------------------------------------------------------------------------
// Tests — RoleQuickSwitch visibility
// --------------------------------------------------------------------------

describe("ConfigForm — RoleQuickSwitch visibility", () => {
  it("does not render quick-switch when showQuickSwitch is false (default)", () => {
    renderForm();

    expect(screen.queryByText("Quick switch")).not.toBeInTheDocument();
  });

  it("does not render quick-switch when showQuickSwitch is explicitly false", () => {
    renderForm({}, { showQuickSwitch: false });

    expect(screen.queryByText("Quick switch")).not.toBeInTheDocument();
  });

  it("renders quick-switch when showQuickSwitch is true", () => {
    renderForm({}, { showQuickSwitch: true });

    expect(screen.getByText("Quick switch")).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Tests — RoleQuickSwitch behavior
// --------------------------------------------------------------------------

describe("ConfigForm — RoleQuickSwitch", () => {
  it("renders two quick-switch buttons: imu and imu-live", () => {
    renderForm({}, { showQuickSwitch: true });

    const buttons = getQuickSwitchButtons();
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveTextContent("imu");
    expect(buttons[1]).toHaveTextContent("imu-live");
  });

  it("calls onSave immediately when switching to a different role", async () => {
    const user = userEvent.setup();
    renderForm({ orchestrator: { role: "imu" } }, { showQuickSwitch: true });

    const buttons = getQuickSwitchButtons();
    await user.click(buttons[1]); // click "imu-live"

    expect(onSave).toHaveBeenCalledTimes(1);
    const savedData = onSave.mock.calls[0][0];
    expect(savedData.orchestrator.role).toBe("imu-live");
  });

  it("does not call onSave when clicking the already-selected role", async () => {
    const user = userEvent.setup();
    renderForm({ orchestrator: { role: "imu" } }, { showQuickSwitch: true });

    const buttons = getQuickSwitchButtons();
    await user.click(buttons[0]); // click "imu" — already selected

    expect(onSave).not.toHaveBeenCalled();
  });

  it("reflects the current role with active styling class", () => {
    renderForm(
      { orchestrator: { role: "imu-live" } },
      { showQuickSwitch: true },
    );

    const buttons = getQuickSwitchButtons();
    // Active button gets bg-background class
    expect(buttons[1].className).toContain("bg-background");
    // Inactive button gets text-muted-foreground
    expect(buttons[0].className).toContain("text-muted-foreground");
    expect(buttons[0].className).not.toContain("bg-background");
  });

  it("disables quick-switch buttons when saving", () => {
    renderForm(
      { orchestrator: { role: "imu" } },
      { saving: true, showQuickSwitch: true },
    );

    const buttons = getQuickSwitchButtons();
    expect(buttons[0]).toBeDisabled();
    expect(buttons[1]).toBeDisabled();
  });

  it("shows no active button when orchestrator_role is a non-quick-role value", () => {
    renderForm(
      { orchestrator: { role: "custom-role" } },
      { showQuickSwitch: true },
    );

    const buttons = getQuickSwitchButtons();
    // Neither button should have the active styling
    for (const btn of buttons) {
      expect(btn.className).not.toContain("bg-background");
      expect(btn.className).toContain("text-muted-foreground");
    }
  });

  it("updates the Role input field value after quick-switch", async () => {
    const user = userEvent.setup();
    renderForm({ orchestrator: { role: "imu" } }, { showQuickSwitch: true });

    // Role input should initially show "imu"
    const roleInput = screen.getByDisplayValue("imu");
    expect(roleInput).toBeInTheDocument();

    // Switch to imu-live
    const buttons = getQuickSwitchButtons();
    await user.click(buttons[1]);

    // Role input should now reflect "imu-live"
    expect(screen.getByDisplayValue("imu-live")).toBeInTheDocument();
  });

  it("preserves other config values when quick-switching roles", async () => {
    const user = userEvent.setup();
    renderForm(
      {
        orchestrator: { role: "imu", permission_mode: "plan" },
        runtime: "my-agent",
      },
      { showQuickSwitch: true },
    );

    const buttons = getQuickSwitchButtons();
    await user.click(buttons[1]); // switch to imu-live

    const savedData = onSave.mock.calls[0][0];
    expect(savedData.orchestrator.role).toBe("imu-live");
    expect(savedData.orchestrator.permission_mode).toBe("plan");
    expect(savedData.runtime).toBe("my-agent");
  });
});
