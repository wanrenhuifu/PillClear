import { render, screen } from "@testing-library/react";
import App from "./App";

it("渲染应用外壳", () => {
  render(<App />);
  expect(screen.getByText("PillClear")).toBeInTheDocument();
});
