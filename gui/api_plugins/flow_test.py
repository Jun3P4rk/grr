#!/usr/bin/env python
"""This module contains tests for flows-related API handlers."""




from grr.gui import api_test_lib
from grr.gui.api_plugins import flow as flow_plugin

from grr.lib import aff4
from grr.lib import flags
from grr.lib import flow
from grr.lib import flow_runner
from grr.lib import output_plugin
from grr.lib import rdfvalue
from grr.lib import test_lib
from grr.lib import throttle
from grr.lib import type_info
from grr.lib import utils
from grr.lib.aff4_objects import collections as aff4_collections
from grr.lib.flows.general import administrative
from grr.lib.flows.general import discovery
from grr.lib.flows.general import file_finder
from grr.lib.flows.general import processes
from grr.lib.flows.general import transfer
from grr.lib.hunts import standard_test
from grr.lib.output_plugins import email_plugin
from grr.lib.rdfvalues import client as rdf_client
from grr.lib.rdfvalues import paths as rdf_paths


class ApiGetFlowStatusHandlerTest(test_lib.GRRBaseTest):
  """Test for ApiGetFlowStatusHandler."""

  def setUp(self):
    super(ApiGetFlowStatusHandlerTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]
    self.handler = flow_plugin.ApiGetFlowStatusHandler()

  def testIsDisabledByDefault(self):
    self.assertFalse(self.handler.enabled_by_default)

  def testParameterValidation(self):
    """Check bad parameters are rejected.

    Make sure our input is validated because this API doesn't require
    authorization.
    """
    bad_flowid = flow_plugin.ApiGetFlowStatusArgs(
        client_id=self.client_id.Basename(), flow_id="X:<script>")
    with self.assertRaises(ValueError):
      self.handler.Render(bad_flowid, token=self.token)

    with self.assertRaises(type_info.TypeValueError):
      flow_plugin.ApiGetFlowStatusArgs(
          client_id="C.123456<script>", flow_id="X:1245678")


class ApiGetFlowStatusHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Test flow status handler.

  This handler is disabled by default in the ACLs so we need to do some
  patching to get the proper output and not just "access denied".
  """
  handler = "ApiGetFlowStatusHandler"

  def Run(self):
    # Fix the time to avoid regressions.
    with test_lib.FakeTime(42):
      client_urn = self.SetupClients(1)[0]

      # Delete the certificates as it's being regenerated every time the
      # client is created.
      with aff4.FACTORY.Open(client_urn, mode="rw",
                             token=self.token) as client_obj:
        client_obj.DeleteAttribute(client_obj.Schema.CERT)

      flow_id = flow.GRRFlow.StartFlow(
          flow_name=discovery.Interrogate.__name__, client_id=client_urn,
          token=self.token)

      # Put something in the output collection
      flow_obj = aff4.FACTORY.Open(flow_id, aff4_type=flow.GRRFlow.__name__,
                                   token=self.token)
      flow_state = flow_obj.Get(flow_obj.Schema.FLOW_STATE)

      with aff4.FACTORY.Create(
          flow_state.context.output_urn,
          aff4_type=aff4_collections.RDFValueCollection.__name__,
          token=self.token) as collection:
        collection.Add(rdf_client.ClientSummary())

      self.Check("GET", "/api/flows/%s/%s/status" % (client_urn.Basename(),
                                                     flow_id.Basename()),
                 replace={flow_id.Basename(): "F:ABCDEF12"})


class ApiListClientFlowsHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Test client flows list handler."""

  handler = "ApiListClientFlowsHandler"

  def Run(self):
    with test_lib.FakeTime(42):
      client_urn = self.SetupClients(1)[0]

    with test_lib.FakeTime(43):
      flow_id_1 = flow.GRRFlow.StartFlow(
          flow_name=discovery.Interrogate.__name__, client_id=client_urn,
          # TODO(user): output="" has to be specified because otherwise
          # output collection object is created and stored in state.context.
          # When AFF4Object is serialized, it gets serialized as
          # <AFF4Object@[address] blah> which breaks the regression, because
          # the address is always different. Storing AFF4Object in a state
          # is bad, and we should use blind writes to write to the output
          # collection. Remove output="" as soon as the issue is resolved.
          output="", token=self.token)

    with test_lib.FakeTime(44):
      flow_id_2 = flow.GRRFlow.StartFlow(
          flow_name=processes.ListProcesses.__name__, client_id=client_urn,
          # TODO(user): See comment above regarding output="".
          output="", token=self.token)

    self.Check("GET", "/api/clients/%s/flows" % client_urn.Basename(),
               replace={flow_id_1.Basename(): "F:ABCDEF10",
                        flow_id_2.Basename(): "F:ABCDEF11"})


class ApiListFlowResultsHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiListFlowResultsHandler."""

  handler = "ApiListFlowResultsHandler"

  def setUp(self):
    super(ApiListFlowResultsHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    runner_args = flow_runner.FlowRunnerArgs(
        flow_name=transfer.GetFile.__name__)

    flow_args = transfer.GetFileArgs(
        pathspec=rdf_paths.PathSpec(
            path="/tmp/evil.txt",
            pathtype=rdf_paths.PathSpec.PathType.OS))

    client_mock = test_lib.SampleHuntMock()

    with test_lib.FakeTime(42):
      flow_urn = flow.GRRFlow.StartFlow(client_id=self.client_id,
                                        args=flow_args,
                                        runner_args=runner_args,
                                        token=self.token)

      for _ in test_lib.TestFlowHelper(flow_urn, client_mock=client_mock,
                                       client_id=self.client_id,
                                       token=self.token):
        pass

    self.Check("GET",
               "/api/clients/%s/flows/%s/results" % (self.client_id.Basename(),
                                                     flow_urn.Basename()),
               replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiGetFlowResultsExportCommandHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiGetFlowResultsExportCommandHandler."""

  handler = "ApiGetFlowResultsExportCommandHandler"

  def setUp(self):
    super(ApiGetFlowResultsExportCommandHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    with test_lib.FakeTime(42):
      flow_urn = flow.GRRFlow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=self.client_id,
          token=self.token)

    self.Check("GET",
               "/api/clients/%s/flows/%s/results/export-command" % (
                   self.client_id.Basename(), flow_urn.Basename()),
               replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiListFlowOutputPluginsHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiListFlowOutputPluginsHandler."""

  handler = "ApiListFlowOutputPluginsHandler"

  def setUp(self):
    super(ApiListFlowOutputPluginsHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    email_descriptor = output_plugin.OutputPluginDescriptor(
        plugin_name=email_plugin.EmailOutputPlugin.__name__,
        plugin_args=email_plugin.EmailOutputPluginArgs(
            email_address="test@localhost", emails_limit=42))

    with test_lib.FakeTime(42):
      flow_urn = flow.GRRFlow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=self.client_id,
          output_plugins=[email_descriptor],
          token=self.token)

    self.Check("GET", "/api/clients/%s/flows/%s/output-plugins" % (
        self.client_id.Basename(), flow_urn.Basename()),
               replace={flow_urn.Basename(): "W:ABCDEF"})


class DummyFlowWithSingleReply(flow.GRRFlow):
  """Just emits 1 reply."""

  @flow.StateHandler()
  def Start(self, unused_response=None):
    self.CallState(next_state="SendSomething")

  @flow.StateHandler()
  def SendSomething(self, unused_response=None):
    self.SendReply(rdfvalue.RDFString("oh"))


class ApiListFlowOutputPluginLogsHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiListFlowOutputPluginLogsHandler."""

  handler = "ApiListFlowOutputPluginLogsHandler"

  def setUp(self):
    super(ApiListFlowOutputPluginLogsHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    email_descriptor = output_plugin.OutputPluginDescriptor(
        plugin_name=email_plugin.EmailOutputPlugin.__name__,
        plugin_args=email_plugin.EmailOutputPluginArgs(
            email_address="test@localhost", emails_limit=42))

    with test_lib.FakeTime(42):
      flow_urn = flow.GRRFlow.StartFlow(
          flow_name=DummyFlowWithSingleReply.__name__,
          client_id=self.client_id,
          output_plugins=[email_descriptor],
          token=self.token)

    with test_lib.FakeTime(43):
      for _ in test_lib.TestFlowHelper(flow_urn, token=self.token):
        pass

    self.Check("GET", "/api/clients/%s/flows/%s/output-plugins/"
               "EmailOutputPlugin_0/logs" % (self.client_id.Basename(),
                                             flow_urn.Basename()),
               replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiListFlowOutputPluginErrorsHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiListFlowOutputPluginErrorsHandler."""

  handler = "ApiListFlowOutputPluginErrorsHandler"

  def setUp(self):
    super(ApiListFlowOutputPluginErrorsHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    failing_descriptor = output_plugin.OutputPluginDescriptor(
        plugin_name=standard_test.FailingDummyHuntOutputPlugin.__name__)

    with test_lib.FakeTime(42):
      flow_urn = flow.GRRFlow.StartFlow(
          flow_name=DummyFlowWithSingleReply.__name__,
          client_id=self.client_id,
          output_plugins=[failing_descriptor],
          token=self.token)

    with test_lib.FakeTime(43):
      for _ in test_lib.TestFlowHelper(flow_urn, token=self.token):
        pass

    self.Check("GET", "/api/clients/%s/flows/%s/output-plugins/"
               "FailingDummyHuntOutputPlugin_0/errors" % (
                   self.client_id.Basename(), flow_urn.Basename()),
               replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiCreateFlowHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiCreateFlowHandler."""

  handler = "ApiCreateFlowHandler"

  def setUp(self):
    super(ApiCreateFlowHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    def ReplaceFlowId():
      flows_dir_fd = aff4.FACTORY.Open(self.client_id.Add("flows"),
                                       token=self.token)
      flow_urn = list(flows_dir_fd.ListChildren())[0]
      return {flow_urn.Basename(): "W:ABCDEF"}

    with test_lib.FakeTime(42):
      self.Check("POST",
                 "/api/clients/%s/flows" % self.client_id.Basename(),
                 {"flow": {
                     "name": processes.ListProcesses.__name__,
                     "args": {
                         "filename_regex": ".",
                         "fetch_binaries": True
                         },
                     "runner_args": {
                         "output_plugins": [],
                         "priority": "HIGH_PRIORITY",
                         "notify_to_user": False,
                         },
                     }
                 }, replace=ReplaceFlowId)


class ApiCancelFlowHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiCancelFlowHandler."""

  handler = "ApiCancelFlowHandler"

  def setUp(self):
    super(ApiCancelFlowHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    with test_lib.FakeTime(42):
      flow_urn = flow.GRRFlow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=self.client_id,
          token=self.token)

    self.Check("POST", "/api/clients/%s/flows/%s/actions/cancel" % (
        self.client_id.Basename(), flow_urn.Basename()),
               replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiListFlowDescriptorsHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  """Regression test for ApiListFlowDescriptorsHandler."""

  handler = "ApiListFlowDescriptorsHandler"

  def Run(self):
    with utils.Stubber(flow.GRRFlow, "classes", {
        "ListProcesses": processes.ListProcesses,
        "FileFinder": file_finder.FileFinder,
        "RunReport": administrative.RunReport
        }):
      # RunReport flow is only shown for admins.
      self.CreateAdminUser("test")

      self.Check("GET", "/api/flows/descriptors")
      self.Check("GET", "/api/flows/descriptors?flow_type=client")
      self.Check("GET", "/api/flows/descriptors?flow_type=global")


class ApiStartGetFileOperationHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  handler = "ApiStartGetFileOperationHandler"

  def setUp(self):
    super(ApiStartGetFileOperationHandlerRegressionTest, self).setUp()
    self.client_id = self.SetupClients(1)[0]

  def Run(self):
    def ReplaceFlowId():
      flows_dir_fd = aff4.FACTORY.Open(self.client_id.Add("flows"),
                                       token=self.token)
      flow_urn = list(flows_dir_fd.ListChildren())[0]
      return {flow_urn.Basename(): "W:ABCDEF"}

    with test_lib.FakeTime(42):
      self.Check(
          "POST",
          "/api/clients/%s/flows/remotegetfile" % self.client_id.Basename(),
          {"hostname": self.client_id.Basename(),
           "paths": ["/tmp/test"]},
          replace=ReplaceFlowId)


class ApiStartGetFileOperationHandlerTest(test_lib.GRRBaseTest):
  """Test for ApiStartGetFileOperationHandler."""

  def setUp(self):
    super(ApiStartGetFileOperationHandlerTest, self).setUp()
    self.client_ids = self.SetupClients(4)
    self.handler = flow_plugin.ApiStartGetFileOperationHandler()

  def testClientLookup(self):
    """When multiple clients match, check we run on the latest one."""
    args = flow_plugin.ApiStartGetFileOperationArgs(
        hostname="Host", paths=["/test"])
    result = self.handler.Render(args, token=self.token)
    self.assertIn("C.1000000000000003", result["status_url"])

  def testThrottle(self):
    """Calling the same flow should raise."""
    args = flow_plugin.ApiStartGetFileOperationArgs(
        hostname="Host", paths=["/test"])
    result = self.handler.Render(args, token=self.token)
    self.assertIn("C.1000000000000003", result["status_url"])

    with self.assertRaises(throttle.ErrorFlowDuplicate):
      self.handler.Render(args, token=self.token)


class ApiArchiveFlowFilesHandlerRegressionTest(
    api_test_lib.ApiCallHandlerRegressionTest):
  handler = "ApiArchiveFlowFilesHandler"

  def setUp(self):
    super(ApiArchiveFlowFilesHandlerRegressionTest, self).setUp()

    self.client_id = self.SetupClients(1)[0]

    with test_lib.FakeTime(41):
      self.file_finder_flow_urn = flow.GRRFlow.StartFlow(
          flow_name=file_finder.FileFinder.__name__,
          client_id=self.client_id,
          paths=["/tmp/evil.txt"],
          action=file_finder.FileFinderAction(action_type="DOWNLOAD"),
          token=self.token)

  def Run(self):
    def ReplaceFlowId():
      flows_dir_fd = aff4.FACTORY.Open(self.client_id.Add("flows"),
                                       token=self.token)

      result = {}
      children = sorted(flows_dir_fd.ListChildren(), key=lambda x: x.age)
      for index, flow_urn in enumerate(children):
        result[flow_urn.Basename()] = "W:ABCDE%d" % index

      return result

    with test_lib.FakeTime(42):
      self.Check(
          "POST",
          "/api/clients/%s/flows/%s/results/archive-files" % (
              self.client_id.Basename(), self.file_finder_flow_urn.Basename()),
          replace=ReplaceFlowId)


def main(argv):
  test_lib.main(argv)


if __name__ == "__main__":
  flags.StartMain(main)
