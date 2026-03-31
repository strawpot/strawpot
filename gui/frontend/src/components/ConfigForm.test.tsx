import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfigForm from "./ConfigForm";

// --------------------------------------------------------------------------
// Mocks
// --------------------------------------------------------------------------

vi.mock("@/hooks/queries/use-registry", () => ({
  useResources: () => ({ data: [] }),
}));

vi.mock("@/hooks/queries/use-project-resources", () => ({
  useProjectResources: () => ({ data: undefined }),
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
  props: { saving?: boolean } = {},
) {
  const values = makeValues(valuesOverrides);
  return render(
    <ConfigForm
      values={values}
      onSave={onSave}
      saving={props.saving}
    />,
  );
}

// --------------------------------------------------------------------------
// Tests — ConfigForm rendering
// --------------------------------------------------------------------------

describe("ConfigForm", () => {
  it("renders the form with all sections", () => {
    renderForm();

    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Orchestrator")).toBeInTheDocument();
    expect(screen.getByText("Policy")).toBeInTheDocument();
    expect(screen.getByText("Session")).toBeInTheDocument();
    expect(screen.getByText("Trace")).toBeInTheDocument();
  });

  it("does not render quick-switch in global settings", () => {
    renderForm();

    expect(screen.queryByText("Quick switch")).not.toBeInTheDocument();
  });

  it("renders Role input with initial value", () => {
    renderForm({ orchestrator: { role: "imu-live" } });

    expect(screen.getByDisplayValue("imu-live")).toBeInTheDocument();
  });

  it("calls onSave with nested config on save button click", async () => {
    const user = userEvent.setup();
    renderForm({
      orchestrator: { role: "imu", permission_mode: "plan" },
      runtime: "my-agent",
    });

    const saveBtn = screen.getByRole("button", { name: /save configuration/i });
    await user.click(saveBtn);

    expect(onSave).toHaveBeenCalledTimes(1);
    const savedData = onSave.mock.calls[0][0];
    expect(savedData.orchestrator.role).toBe("imu");
    expect(savedData.orchestrator.permission_mode).toBe("plan");
    expect(savedData.runtime).toBe("my-agent");
  });

  it("disables save button when saving", () => {
    renderForm({}, { saving: true });

    const saveBtn = screen.getByRole("button", { name: /saving/i });
    expect(saveBtn).toBeDisabled();
  });
});
